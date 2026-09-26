"""Owner-scoped history, keyset pagination, and atomic successful turns."""
import base64
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from uuid import UUID, uuid4

from sqlalchemy import and_, delete, insert, or_, select, text, update
from sqlalchemy.orm import Session

from app.schemas.chat import ConversationDetail, ConversationList, ConversationMessage, ConversationSummary
from app.tenancy.bootstrap import validate_schema_name
from app.tenancy.runtime import get_tenant_tables
from app.utils.exceptions import AppError

RETENTION = timedelta(days=15)


def utcnow():
    return datetime.now(timezone.utc)


def aware(value):
    # SQLite test timestamps have no tzinfo; PostgreSQL stores timestamptz.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


@dataclass(frozen=True)
class ChatActor:
    user_id: UUID
    schema_name: str

    def __post_init__(self):
        validate_schema_name(self.schema_name)


def _encode(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode()


def _decode(cursor):
    try:
        if len(cursor) > 512:
            raise ValueError()
        return json.loads(base64.b64decode(cursor, altchars=b"-_", validate=True))
    except (ValueError, TypeError, UnicodeError) as exc:
        raise AppError(422, "Invalid pagination cursor", "invalid_cursor") from exc


def limit_transaction(db, seconds=5):
    """Bound query and lock waits on the current PostgreSQL transaction."""
    if db.get_bind().dialect.name == "postgresql":
        milliseconds = str(max(1, int(seconds * 1000)))
        db.execute(text("SELECT set_config('statement_timeout', :ms, true), "
                        "set_config('lock_timeout', :ms, true)"), {"ms": milliseconds})


class ConversationStore:
    def __init__(self, db: Session, actor: ChatActor):
        self.db, self.actor = db, actor
        tables = get_tenant_tables(actor.schema_name)
        self.conversations, self.messages = tables["chat_conversation"], tables["chat_message"]

    def _owned(self, now):
        c = self.conversations.c
        return and_(c.usuario_id == self.actor.user_id, c.expires_at > now)

    def load(self, conversation_id, *, now=None):
        row = self.db.execute(select(self.conversations).where(
            self.conversations.c.id == conversation_id, self._owned(now or utcnow())
        )).mappings().first()
        if row is None:
            raise AppError(404, "Conversation not found", "conversation_not_found")
        return dict(row)

    @staticmethod
    def summary(row):
        return ConversationSummary(**{**row, **{
            key: aware(row[key]) for key in ("created_at", "last_message_at", "expires_at")
        }})

    def list(self, *, limit=20, cursor=None):
        c = self.conversations.c
        query = select(self.conversations).where(self._owned(utcnow()))
        if cursor:
            try:
                value = _decode(cursor)
                if not isinstance(value, list) or len(value) != 2 or not all(isinstance(part, str) for part in value):
                    raise ValueError()
                stamp, identity = value
                stamp, identity = datetime.fromisoformat(stamp), UUID(identity)
                if stamp.tzinfo is None:
                    raise ValueError()
            except (ValueError, TypeError) as exc:
                raise AppError(422, "Invalid pagination cursor", "invalid_cursor") from exc
            query = query.where(or_(c.last_message_at < stamp, and_(c.last_message_at == stamp, c.id < identity)))
        rows = self.db.execute(query.order_by(c.last_message_at.desc(), c.id.desc()).limit(limit + 1)).mappings().all()
        items = [self.summary(row) for row in rows[:limit]]
        next_cursor = _encode([items[-1].last_message_at.isoformat(), str(items[-1].id)]) if len(rows) > limit else None
        return ConversationList(items=items, next_cursor=next_cursor)

    def detail(self, conversation_id, *, limit=50, cursor=None):
        conversation = self.load(conversation_id)
        m = self.messages.c
        query = select(self.messages).where(m.conversation_id == conversation_id)
        if cursor:
            value = _decode(cursor)
            if type(value) is not int or not 0 < value <= 2147483647:
                raise AppError(422, "Invalid pagination cursor", "invalid_cursor")
            query = query.where(m.sequence < value)
        rows = self.db.execute(query.order_by(m.sequence.desc()).limit(limit + 1)).mappings().all()
        page = rows[:limit]
        return ConversationDetail(
            conversation=self.summary(conversation),
            messages=[ConversationMessage(**{**r, "created_at": aware(r["created_at"])}) for r in reversed(page)],
            next_cursor=_encode(page[-1]["sequence"]) if len(rows) > limit else None,
        )

    def history(self, conversation_id):
        """The model sees at most ten recent complete turns and 16,000 characters."""
        m = self.messages.c
        rows = self.db.execute(select(m.role, m.content, m.created_at, m.sources, m.limitations).select_from(
            self.messages.join(self.conversations, m.conversation_id == self.conversations.c.id)
        ).where(m.conversation_id == conversation_id, self._owned(utcnow()))
          .order_by(m.sequence.desc()).limit(21)).all()
        selected, size = [], 0
        for row in rows[:20]:
            content = row.content
            if row.role == "assistant":
                # Preserve the actual prior period for "that period" follow-ups,
                # without replaying raw tool data or presenting old figures as fresh.
                content += "\n\n[Previous reply metadata; query tools again for fresh figures]\n" + json.dumps({
                    "created_at": aware(row.created_at).isoformat(),
                    "sources": row.sources, "limitations": row.limitations,
                }, ensure_ascii=False)
            if size + len(content) > 16000:
                break
            selected.append({"role": row.role, "content": content})
            size += len(content)
        selected.reverse()
        if selected and selected[0]["role"] != "user":
            selected.pop(0)
        return selected, len(rows) > len(selected)

    def append_turn(self, *, conversation, question, answer, sources, limitations, now=None):
        now = now or utcnow()
        expires = now + RETENTION
        c = self.conversations.c
        identity = conversation["id"] if conversation else uuid4()
        revision = conversation["revision"] if conversation else 0
        try:
            if conversation:
                result = self.db.execute(update(self.conversations).where(
                    c.id == identity, self._owned(now), c.revision == revision
                ).values(revision=revision + 1, last_message_at=now, expires_at=expires))
                if result.rowcount != 1:
                    # Distinguish a stale concurrent turn from deletion or expiry.
                    self.load(identity, now=now)
                    raise AppError(409, "Conversation changed; reload before sending again", "conversation_conflict")
            else:
                self.db.execute(insert(self.conversations).values(
                    id=identity, usuario_id=self.actor.user_id, title=question[:120],
                    created_at=now, last_message_at=now, expires_at=expires, revision=1,
                ))
            answer_id = uuid4()
            self.db.execute(insert(self.messages), [
                dict(id=uuid4(), conversation_id=identity, sequence=revision * 2 + 1, role="user",
                     content=question, created_at=now, sources=[], limitations=[]),
                dict(id=answer_id, conversation_id=identity, sequence=revision * 2 + 2, role="assistant",
                     content=answer, created_at=now, sources=sources, limitations=limitations),
            ])
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return identity, answer_id, now, expires

    def delete(self, conversation_id):
        result = self.db.execute(delete(self.conversations).where(
            self.conversations.c.id == conversation_id, self._owned(utcnow())
        ))
        if result.rowcount != 1:
            self.db.rollback()
            raise AppError(404, "Conversation not found", "conversation_not_found")
        self.db.commit()
