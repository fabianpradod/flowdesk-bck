from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import Column, DateTime, MetaData, String, Table, Text
from sqlalchemy.dialects.postgresql import UUID

from app.models.tenant.operations import Task, Tarea
from app.schemas.tasks import TaskCreate, TaskStatusUpdate, TaskUpdate
from app.services.tasks import (
    create_task,
    delete_task,
    get_task,
    list_tasks,
    update_task,
    update_task_status,
)
from app.utils.exceptions import AppError


SCHEMA_NAME = "tenant_1234567890abcdef1234567890abcdef"


def test_task_model_keeps_the_existing_tenant_table_name():
    assert Task is Tarea
    assert Task.__tablename__ == "tarea"
    assert Task.__table__.schema == "tenant"


def test_task_schema_normalizes_text_and_defaults_priority():
    task = TaskCreate(titulo="  Preparar pedido  ", descripcion="  Para mañana  ")

    assert task.titulo == "Preparar pedido"
    assert task.descripcion == "Para mañana"
    assert task.prioridad == "media"


def test_task_schema_rejects_unknown_status():
    with pytest.raises(ValidationError):
        TaskStatusUpdate(estado="desconocido")


def test_task_update_requires_at_least_one_field():
    with pytest.raises(ValidationError):
        TaskUpdate()


@pytest.mark.parametrize("payload", [{"titulo": None}, {"prioridad": None}])
def test_task_update_rejects_null_for_required_database_fields(payload):
    with pytest.raises(ValidationError):
        TaskUpdate(**payload)


def test_create_task_assigns_the_authenticated_user_and_pending_status():
    user = tenant_user()
    created = task_row(user_id=user.id)
    db = FakeDB([FakeResult([]), FakeResult([created])])

    with patch("app.services.tasks.get_tenant_tables", return_value=tenant_tables()):
        result = create_task(TaskCreate(titulo="Nueva tarea"), user, db)

    assert result == created
    assert db.commits == 1
    params = db.executed[0].compile().params
    assert params["usuario_id"] == user.id
    assert params["estado"] == "pendiente"


def test_list_tasks_is_owner_scoped_and_supports_filters():
    user = tenant_user()
    db = FakeDB([FakeResult([task_row(user_id=user.id)])])

    with patch("app.services.tasks.get_tenant_tables", return_value=tenant_tables()):
        rows = list_tasks(
            user,
            db,
            estado="pendiente",
            prioridad="alta",
            search=" pedido ",
        )

    assert len(rows) == 1
    query = db.executed[0]
    rendered = str(query).lower()
    params = query.compile().params
    assert "usuario_id" in rendered
    assert "estado" in rendered
    assert "prioridad" in rendered
    assert "%pedido%" in params.values()
    assert user.id in params.values()


def test_get_task_hides_tasks_not_owned_by_the_user():
    db = FakeDB([FakeResult([])])

    with patch("app.services.tasks.get_tenant_tables", return_value=tenant_tables()):
        with pytest.raises(AppError) as error:
            get_task(uuid4(), tenant_user(), db)

    assert error.value.status_code == 404
    assert error.value.detail == "Task not found"


def test_update_task_writes_only_sent_fields_and_preserves_ownership_scope():
    user = tenant_user()
    existing = task_row(user_id=user.id)
    updated = {**existing, "prioridad": "alta"}
    db = FakeDB(
        [
            FakeResult([existing]),
            FakeResult([]),
            FakeResult([updated]),
        ]
    )

    with patch("app.services.tasks.get_tenant_tables", return_value=tenant_tables()):
        result = update_task(
            existing["id"],
            TaskUpdate(prioridad="alta"),
            user,
            db,
        )

    assert result["prioridad"] == "alta"
    params = db.executed[1].compile().params
    assert "prioridad" in params
    assert "updated_at" in params
    assert "titulo" not in params
    assert user.id in params.values()


def test_update_task_status_persists_an_allowed_status():
    user = tenant_user()
    existing = task_row(user_id=user.id)
    completed = {**existing, "estado": "completada"}
    db = FakeDB(
        [
            FakeResult([existing]),
            FakeResult([]),
            FakeResult([completed]),
        ]
    )

    with patch("app.services.tasks.get_tenant_tables", return_value=tenant_tables()):
        result = update_task_status(
            existing["id"],
            "completada",
            user,
            db,
        )

    assert result["estado"] == "completada"
    assert db.commits == 1


def test_delete_task_deletes_only_the_owned_record():
    user = tenant_user()
    existing = task_row(user_id=user.id)
    db = FakeDB([FakeResult([existing]), FakeResult([])])

    with patch("app.services.tasks.get_tenant_tables", return_value=tenant_tables()):
        delete_task(existing["id"], user, db)

    assert db.commits == 1
    rendered = str(db.executed[1]).lower()
    params = db.executed[1].compile().params
    assert "delete from" in rendered
    assert user.id in params.values()


def test_task_routes_are_documented(client):
    paths = client.get("/openapi.json").json()["paths"]

    assert set(paths["/api/v1/tasks"]) == {"get", "post"}
    assert set(paths["/api/v1/tasks/{task_id}"]) == {"get", "put", "delete"}
    assert set(paths["/api/v1/tasks/{task_id}/status"]) == {"patch"}


def tenant_user():
    return SimpleNamespace(
        id=uuid4(),
        company_id=uuid4(),
        company=SimpleNamespace(is_active=True, schema_name=SCHEMA_NAME),
    )


def task_row(*, user_id):
    now = datetime.now(timezone.utc)
    return {
        "id": uuid4(),
        "usuario_id": user_id,
        "titulo": "Preparar pedido",
        "descripcion": None,
        "fecha_limite": None,
        "estado": "pendiente",
        "prioridad": "media",
        "created_at": now,
        "updated_at": now,
    }


def tenant_tables():
    metadata = MetaData()
    Table(
        "tarea",
        metadata,
        Column("id", UUID(as_uuid=True), primary_key=True),
        Column("usuario_id", UUID(as_uuid=True), nullable=False),
        Column("titulo", String(100), nullable=False),
        Column("descripcion", Text, nullable=True),
        Column("fecha_limite", DateTime, nullable=True),
        Column("estado", String(20), nullable=False),
        Column("prioridad", String(20), nullable=False),
        Column("created_at", DateTime, nullable=False),
        Column("updated_at", DateTime, nullable=False),
        schema=SCHEMA_NAME,
    )
    return {
        table.name: table
        for table in metadata.tables.values()
        if table.schema == SCHEMA_NAME
    }


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


class FakeDB:
    def __init__(self, results):
        self.results = list(results)
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, statement, *_args, **_kwargs):
        self.executed.append(statement)
        return self.results.pop(0) if self.results else FakeResult([])

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1
