from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.schemas.commercial import ClientCreate, ClientUpdate
from app.tenancy.runtime import get_tenant_tables, get_user_schema_name
from app.utils.exceptions import AppError

def list_clients(
    current_user,
    db: Session,
    *,
    search: str | None = None,
    active_only: bool = True,
) -> list[dict]:
    clients = _clients_table(current_user)
    query = select(clients).order_by(clients.c.nombre.asc())
    if active_only:
        query = query.where(clients.c.is_active.is_(True))
    if search:
        term = f"%{search.strip().lower()}%"
        query = query.where(
            or_(
                func.lower(clients.c.nombre).like(term),
                func.lower(clients.c.correo).like(term),
                func.lower(clients.c.telefono).like(term),
            )
        )
    rows = db.execute(query).mappings()
    return [dict(row) for row in rows]


def get_client(client_id: UUID, current_user, db: Session) -> dict:
    clients = _clients_table(current_user)
    row = db.execute(select(clients).where(clients.c.id == client_id)).mappings().first()
    if row is None:
        raise AppError(status_code=404, message="Client not found")
    return dict(row)


def create_client(data: ClientCreate, current_user, db: Session) -> dict:
    clients = _clients_table(current_user)
    payload = _client_payload(data)
    _ensure_email_available(db, clients, payload.get("correo"))

    now = _utcnow()
    client_id = uuid4()
    try:
        db.execute(
            insert(clients).values(
                id=client_id,
                **payload,
                updated_at=now,
            )
        )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise AppError(
            status_code=500,
            message="Database error while creating client",
        ) from exc

    except Exception as exc:
        db.rollback()
        raise AppError(
            status_code=500,
            message="Server error while creating client",
        ) from exc

    return get_client(client_id, current_user, db)


def update_client(client_id: UUID, data: ClientUpdate, current_user, db: Session) -> dict:
    clients = _clients_table(current_user)
    _ensure_client_exists(db, clients, client_id)
    payload = _client_payload(data, exclude_unset=True)
    if not payload:
        raise AppError(status_code=400, message="At least one field must be provided")

    if "correo" in payload:
        _ensure_email_available(db, clients, payload.get("correo"), exclude_client_id=client_id)

    try:
        db.execute(
            update(clients)
            .where(clients.c.id == client_id)
            .values(**payload, updated_at=_utcnow())
        )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise AppError(
            status_code=500,
            message="Database error while updating client",
        ) from exc
    except Exception as exc:
        db.rollback()
        raise AppError(
            status_code=500,
            message="Server error while updating client",
        ) from exc

    return get_client(client_id, current_user, db)


def update_client_status(client_id: UUID, is_active: bool, current_user, db: Session) -> dict:
    clients = _clients_table(current_user)
    current = db.execute(select(clients).where(clients.c.id == client_id)).mappings().first()

    if current is None:
        raise AppError(status_code=404, message="Client not found",)

    if current["is_active"] == is_active:
        raise AppError(status_code=400, message="Client already has this status",)

    _ensure_client_exists(db, clients, client_id)
    try:
        db.execute(
            update(clients)
            .where(clients.c.id == client_id)
            .values(is_active=is_active, updated_at=_utcnow())
        )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise AppError(
            status_code=500,
            message="Database error while updating client status",
        ) from exc
    except Exception as exc:
        db.rollback()
        raise AppError(
            status_code=500,
            message="Server error while updating client status",
        ) from exc

    return get_client(client_id, current_user, db)


def delete_client(client_id: UUID, current_user, db: Session) -> None:
    clients = _clients_table(current_user)
    _ensure_client_exists(db, clients, client_id)
    try:
        db.execute(
            update(clients)
            .where(clients.c.id == client_id)
            .values(is_active=False, updated_at=_utcnow())
        )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise AppError(
            status_code=500,
            message="Database error while deleting client",
        ) from exc
    except Exception as exc:
        db.rollback()
        raise AppError(
            status_code=500,
            message="Server error while deleting client",
        ) from exc


def _clients_table(current_user):
    schema_name = get_user_schema_name(current_user)
    return get_tenant_tables(schema_name)["cliente"]


def _client_payload(data, *, exclude_unset: bool = False) -> dict:
    raw = data.model_dump(exclude_unset=exclude_unset)
    payload = {}
    for key, value in raw.items():
        if value is None:
            payload[key] = None
        elif key == "correo":
            payload[key] = str(value).strip().lower()
        else:
            payload[key] = str(value).strip()
    return payload


def _ensure_email_available(db: Session, clients, correo: str | None, *, exclude_client_id: UUID | None = None) -> None:
    if not correo:
        return
    query = select(clients.c.id).where(func.lower(clients.c.correo) == correo.lower())
    if exclude_client_id is not None:
        query = query.where(clients.c.id != exclude_client_id)
    existing = db.execute(query).first()
    if existing:
        raise AppError(status_code=400, message="Client email already exists")


def _ensure_client_exists(db: Session, clients, client_id: UUID) -> None:
    existing = db.execute(select(clients.c.id).where(clients.c.id == client_id)).first()
    if not existing:
        raise AppError(status_code=404, message="Client not found")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
