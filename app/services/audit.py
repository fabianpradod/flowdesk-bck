"""Successful critical changes only; event and mutation share one transaction.

No request bodies, passwords, tokens, personal names or arbitrary metadata are
accepted by this interface. Failure to persist an event must abort the change.
"""
from datetime import datetime, timezone
from uuid import uuid4
from sqlalchemy import insert, select, tuple_
from app.tenancy.runtime import get_tenant_tables, get_user_schema_name
from app.services.pagination import decode_cursor, encode_cursor


def record_event(db, actor, action, entity_type, entity_id, *, schema_name=None):
    schema = schema_name or get_user_schema_name(actor)
    table = get_tenant_tables(schema)['audit_event']
    db.execute(insert(table).values(
        id=uuid4(), occurred_at=datetime.now(timezone.utc).replace(tzinfo=None),
        actor_id=actor.id, action=action, entity_type=entity_type, entity_id=entity_id,
    ))


def list_events(actor, db, *, limit=50, cursor=None, action=None, actor_id=None):
    schema = get_user_schema_name(actor)
    table = get_tenant_tables(schema)['audit_event']
    context = ['audit', str(actor.company_id), action, str(actor_id) if actor_id else None]
    query = select(table)
    if action:
        query = query.where(table.c.action == action)
    if actor_id:
        query = query.where(table.c.actor_id == actor_id)
    if cursor:
        timestamp, event_id = decode_cursor(cursor, context)
        query = query.where(tuple_(table.c.occurred_at, table.c.id) < tuple_(timestamp, event_id))
    rows = [dict(row) for row in db.execute(query.order_by(
        table.c.occurred_at.desc(), table.c.id.desc()).limit(limit + 1)).mappings()]
    items = rows[:limit]
    return {'items': items, 'next_cursor':
            encode_cursor(items[-1], 'occurred_at', context) if len(rows) > limit else None}
