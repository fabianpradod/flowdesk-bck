from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import delete, func, insert, or_, select, update
from sqlalchemy.orm import Session

from app.models.users import User
from app.schemas.tasks import TaskCreate, TaskPriority, TaskStatus, TaskUpdate
from app.tenancy.runtime import get_tenant_tables, get_user_schema_name
from app.utils.exceptions import AppError


def list_tasks(
    current_user: User,
    db: Session,
    *,
    estado: TaskStatus | None = None,
    prioridad: TaskPriority | None = None,
    search: str | None = None,
) -> list[dict]:
    tasks = _tasks_table(current_user)
    query = select(tasks).where(tasks.c.usuario_id == current_user.id)

    if estado is not None:
        query = query.where(tasks.c.estado == estado)
    if prioridad is not None:
        query = query.where(tasks.c.prioridad == prioridad)
    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        query = query.where(
            or_(
                func.lower(tasks.c.titulo).like(term),
                func.lower(tasks.c.descripcion).like(term),
            )
        )

    rows = db.execute(query.order_by(tasks.c.created_at.desc())).mappings()
    return [dict(row) for row in rows]


def get_task(task_id: UUID, current_user: User, db: Session) -> dict:
    tasks = _tasks_table(current_user)
    return _fetch_owned_task(db, tasks, task_id, current_user.id)


def create_task(data: TaskCreate, current_user: User, db: Session) -> dict:
    tasks = _tasks_table(current_user)
    task_id = uuid4()
    now = _utcnow()

    try:
        db.execute(
            insert(tasks).values(
                id=task_id,
                usuario_id=current_user.id,
                **data.model_dump(),
                estado="pendiente",
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return _fetch_owned_task(db, tasks, task_id, current_user.id)


def update_task(
    task_id: UUID,
    data: TaskUpdate,
    current_user: User,
    db: Session,
) -> dict:
    tasks = _tasks_table(current_user)
    _fetch_owned_task(db, tasks, task_id, current_user.id)
    changes = data.model_dump(exclude_unset=True)
    if not changes:
        raise AppError(status_code=400, message="At least one field must be provided")

    try:
        db.execute(
            update(tasks)
            .where(tasks.c.id == task_id, tasks.c.usuario_id == current_user.id)
            .values(**changes, updated_at=_utcnow())
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return _fetch_owned_task(db, tasks, task_id, current_user.id)


def update_task_status(
    task_id: UUID,
    estado: TaskStatus,
    current_user: User,
    db: Session,
) -> dict:
    tasks = _tasks_table(current_user)
    _fetch_owned_task(db, tasks, task_id, current_user.id)

    try:
        db.execute(
            update(tasks)
            .where(tasks.c.id == task_id, tasks.c.usuario_id == current_user.id)
            .values(estado=estado, updated_at=_utcnow())
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return _fetch_owned_task(db, tasks, task_id, current_user.id)


def delete_task(task_id: UUID, current_user: User, db: Session) -> None:
    tasks = _tasks_table(current_user)
    _fetch_owned_task(db, tasks, task_id, current_user.id)

    try:
        db.execute(
            delete(tasks).where(
                tasks.c.id == task_id,
                tasks.c.usuario_id == current_user.id,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise


def _tasks_table(current_user: User):
    schema_name = get_user_schema_name(current_user)
    return get_tenant_tables(schema_name)["tarea"]


def _fetch_owned_task(db: Session, tasks, task_id: UUID, user_id: UUID) -> dict:
    row = db.execute(
        select(tasks).where(
            tasks.c.id == task_id,
            tasks.c.usuario_id == user_id,
        )
    ).mappings().first()
    if row is None:
        raise AppError(status_code=404, message="Task not found")
    return dict(row)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
