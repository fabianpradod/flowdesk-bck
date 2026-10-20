from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID as PythonUUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Column, DateTime, MetaData, String, Table, Text, Uuid, create_engine, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.dependencies.auth import get_current_user, get_db
from app.api.v1.routes.tasks import router as tasks_router
from app.models.tenant.operations import Task, Tarea
from app.services import tasks as task_service
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

@pytest.fixture
def task_persistence_db(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata = MetaData()
    tasks = Table(
        "tarea",
        metadata,
        Column("id", Uuid(as_uuid=True), primary_key=True),
        Column("usuario_id", Uuid(as_uuid=True), nullable=False),
        Column("titulo", String(100), nullable=False),
        Column("descripcion", Text, nullable=True),
        Column("fecha_limite", DateTime, nullable=True),
        Column("estado", String(20), nullable=False),
        Column("prioridad", String(20), nullable=False),
        Column("created_at", DateTime, nullable=False),
        Column("updated_at", DateTime, nullable=False),
    )
    metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = SessionLocal()
    user = tenant_user()

    monkeypatch.setattr(task_service, "_tasks_table", lambda _current_user: tasks)

    yield db, SessionLocal, tasks, user

    db.close()
    engine.dispose()


@pytest.fixture
def task_isolation_db(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata = MetaData()
    tenant_a = "tenant_a"
    tenant_b = "tenant_b"
    with engine.begin() as connection:
        connection.exec_driver_sql('ATTACH DATABASE ":memory:" AS tenant_a')
        connection.exec_driver_sql('ATTACH DATABASE ":memory:" AS tenant_b')

    def task_table(schema_name):
        return Table(
            "tarea",
            metadata,
            Column("id", Uuid(as_uuid=True), primary_key=True),
            Column("usuario_id", Uuid(as_uuid=True), nullable=False),
            Column("titulo", String(100), nullable=False),
            Column("descripcion", Text, nullable=True),
            Column("fecha_limite", DateTime, nullable=True),
            Column("estado", String(20), nullable=False),
            Column("prioridad", String(20), nullable=False),
            Column("created_at", DateTime, nullable=False),
            Column("updated_at", DateTime, nullable=False),
            schema=schema_name,
        )

    tasks_a = task_table(tenant_a)
    tasks_b = task_table(tenant_b)
    metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    db = SessionLocal()
    user_a = tenant_user(tenant_a)
    user_a2 = tenant_user(tenant_a)
    user_b = tenant_user(tenant_b)
    tables = {tenant_a: tasks_a, tenant_b: tasks_b}

    monkeypatch.setattr(
        task_service,
        "get_tenant_tables",
        lambda schema_name: {"tarea": tables[schema_name]},
    )

    yield db, SessionLocal, tables, user_a, user_a2, user_b

    db.close()
    engine.dispose()

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

def test_create_task_persists_and_is_recovered_by_service_in_a_new_session(task_persistence_db):
    db, SessionLocal, tasks, user = task_persistence_db
    due_at = datetime(2026, 5, 1, 12, 30)

    created = create_task(
        TaskCreate(
            titulo="Persisted task",
            descripcion="Created through the task service",
            fecha_limite=due_at,
            prioridad="alta",
        ),
        user,
        db,
    )

    assert created["id"] is not None
    task_id = created["id"]
    db.close()

    reopened = SessionLocal()
    try:
        recovered = get_task(task_id, user, reopened)
        assert recovered["id"] == task_id
        assert recovered["usuario_id"] == user.id
        assert recovered["titulo"] == "Persisted task"
        assert recovered["descripcion"] == "Created through the task service"
        assert recovered["fecha_limite"] == due_at
        assert recovered["estado"] == "pendiente"
        assert recovered["prioridad"] == "alta"
        assert recovered["created_at"] is not None
        assert recovered["updated_at"] is not None

        stored = reopened.execute(
            select(tasks).where(tasks.c.id == task_id)
        ).mappings().one()
        assert stored["titulo"] == "Persisted task"
        assert stored["usuario_id"] == user.id
    finally:
        reopened.close()

def test_create_task_endpoint_returns_id_and_get_recovers_after_request_session(task_persistence_db):
    db, SessionLocal, tasks, user = task_persistence_db
    app = FastAPI()
    app.include_router(tasks_router)
    request_sessions = []

    def request_db():
        session = SessionLocal()
        request_sessions.append(session)
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = request_db
    app.dependency_overrides[get_current_user] = lambda: user

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/tasks",
                json={
                    "titulo": "Endpoint task",
                    "descripcion": "Created over HTTP",
                    "fecha_limite": "2026-06-15T09:45:00",
                    "prioridad": "urgente",
                },
            )
            assert response.status_code == 201, response.text
            payload = response.json()
            assert payload["id"]
            assert payload["titulo"] == "Endpoint task"
            assert payload["descripcion"] == "Created over HTTP"
            assert payload["estado"] == "pendiente"
            assert payload["prioridad"] == "urgente"

            recovered_response = client.get(f"/api/v1/tasks/{payload['id']}")
            assert recovered_response.status_code == 200, recovered_response.text
            assert recovered_response.json()["id"] == payload["id"]
            assert recovered_response.json()["titulo"] == "Endpoint task"
            assert recovered_response.json()["descripcion"] == "Created over HTTP"
    finally:
        app.dependency_overrides.clear()

    db.close()
    reopened = SessionLocal()
    try:
        stored = reopened.execute(
            select(tasks).where(tasks.c.id == PythonUUID(payload["id"]))
        ).mappings().one()
        assert stored["titulo"] == "Endpoint task"
        assert stored["descripcion"] == "Created over HTTP"
        assert stored["prioridad"] == "urgente"
        assert stored["estado"] == "pendiente"
        assert stored["usuario_id"] == user.id
    finally:
        reopened.close()

def test_update_task_persists_all_mutable_fields_in_a_new_session(task_persistence_db):
    db, SessionLocal, _tasks, user = task_persistence_db
    created = create_task(
        TaskCreate(
            titulo="Original title",
            descripcion="Original description",
            fecha_limite=datetime(2026, 5, 1, 12, 30),
            prioridad="baja",
        ),
        user,
        db,
    )
    task_id = created["id"]
    db.close()

    update_session = SessionLocal()
    try:
        updated = update_task(
            task_id,
            TaskUpdate(
                titulo="Updated title",
                descripcion="Updated description",
                fecha_limite=datetime(2026, 7, 15, 9, 0),
                prioridad="urgente",
            ),
            user,
            update_session,
        )
        assert updated["titulo"] == "Updated title"
        assert updated["descripcion"] == "Updated description"
        assert updated["fecha_limite"] == datetime(2026, 7, 15, 9, 0)
        assert updated["prioridad"] == "urgente"
    finally:
        update_session.close()

    reopened = SessionLocal()
    try:
        recovered = get_task(task_id, user, reopened)
        assert recovered["titulo"] == "Updated title"
        assert recovered["descripcion"] == "Updated description"
        assert recovered["fecha_limite"] == datetime(2026, 7, 15, 9, 0)
        assert recovered["prioridad"] == "urgente"
        assert recovered["estado"] == "pendiente"
    finally:
        reopened.close()

def test_update_status_and_delete_persist_after_closing_the_writing_session(task_persistence_db):
    db, SessionLocal, _tasks, user = task_persistence_db
    created = create_task(TaskCreate(titulo="Lifecycle task"), user, db)
    task_id = created["id"]
    db.close()

    status_session = SessionLocal()
    try:
        changed = update_task_status(task_id, "completada", user, status_session)
        assert changed["estado"] == "completada"
    finally:
        status_session.close()

    verify_status = SessionLocal()
    try:
        assert get_task(task_id, user, verify_status)["estado"] == "completada"
    finally:
        verify_status.close()

    delete_session = SessionLocal()
    try:
        delete_task(task_id, user, delete_session)
    finally:
        delete_session.close()

    verify_deletion = SessionLocal()
    try:
        with pytest.raises(AppError) as error:
            get_task(task_id, user, verify_deletion)
        assert error.value.status_code == 404
        assert error.value.detail == "Task not found"
    finally:
        verify_deletion.close()

def test_update_task_rolls_back_when_database_write_fails(task_persistence_db):
    db, SessionLocal, _tasks, user = task_persistence_db
    created = create_task(
        TaskCreate(titulo="Stable title", descripcion="Stable description"),
        user,
        db,
    )
    task_id = created["id"]
    original_execute = db.execute
    original_rollback = db.rollback
    calls = 0
    rollback_calls = []

    def failing_execute(statement, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic database failure")
        return original_execute(statement, *args, **kwargs)

    def recording_rollback():
        rollback_calls.append(True)
        return original_rollback()

    db.execute = failing_execute
    db.rollback = recording_rollback
    with pytest.raises(RuntimeError, match="synthetic database failure"):
        update_task(task_id, TaskUpdate(titulo="Must not persist"), user, db)
    assert len(rollback_calls) == 1
    db.close()

    reopened = SessionLocal()
    try:
        recovered = get_task(task_id, user, reopened)
        assert recovered["titulo"] == "Stable title"
        assert recovered["descripcion"] == "Stable description"
    finally:
        reopened.close()

def test_tasks_are_isolated_between_tenant_contexts(task_isolation_db):
    db, SessionLocal, tables, user_a, _user_a2, user_b = task_isolation_db
    task_a = create_task(TaskCreate(titulo="Empresa A task"), user_a, db)
    task_b = create_task(TaskCreate(titulo="Empresa B task"), user_b, db)
    db.close()

    session_a = SessionLocal()
    session_b = SessionLocal()
    try:
        assert get_task(task_a["id"], user_a, session_a)["titulo"] == "Empresa A task"
        assert get_task(task_b["id"], user_b, session_b)["titulo"] == "Empresa B task"

        with pytest.raises(AppError) as error_b_reading_a:
            get_task(task_a["id"], user_b, session_b)
        assert error_b_reading_a.value.status_code == 404

        with pytest.raises(AppError) as error_a_reading_b:
            get_task(task_b["id"], user_a, session_a)
        assert error_a_reading_b.value.status_code == 404
    finally:
        session_a.close()
        session_b.close()


def test_cross_tenant_http_read_update_and_delete_do_not_mutate_task(task_isolation_db):
    db, SessionLocal, tables, user_a, _user_a2, user_b = task_isolation_db
    task_a = create_task(
        TaskCreate(
            titulo="Original A title",
            descripcion="Original A description",
            prioridad="alta",
        ),
        user_a,
        db,
    )
    create_task(TaskCreate(titulo="Empresa B task"), user_b, db)
    db.close()

    app = FastAPI()
    app.include_router(tasks_router)
    active_user = {"value": user_a}
    request_sessions = []

    def request_db():
        session = SessionLocal()
        request_sessions.append(session)
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = request_db
    app.dependency_overrides[get_current_user] = lambda: active_user["value"]

    try:
        with TestClient(app) as client:
            own_response = client.get(f"/api/v1/tasks/{task_a['id']}")
            assert own_response.status_code == 200
            assert own_response.json()["titulo"] == "Original A title"

            active_user["value"] = user_b
            cross_read = client.get(f"/api/v1/tasks/{task_a['id']}")
            assert cross_read.status_code == 404
            assert "Original A title" not in cross_read.text
            assert "Original A description" not in cross_read.text

            cross_update = client.put(
                f"/api/v1/tasks/{task_a['id']}",
                json={"titulo": "Unauthorized update", "prioridad": "urgente"},
            )
            assert cross_update.status_code == 404
            assert "Unauthorized update" not in cross_update.text

            cross_delete = client.delete(f"/api/v1/tasks/{task_a['id']}")
            assert cross_delete.status_code == 404
    finally:
        app.dependency_overrides.clear()

    reopened = SessionLocal()
    try:
        stored = reopened.execute(
            select(tables[user_a.company.schema_name]).where(
                tables[user_a.company.schema_name].c.id == task_a["id"]
            )
        ).mappings().one()
        assert stored["titulo"] == "Original A title"
        assert stored["descripcion"] == "Original A description"
        assert stored["prioridad"] == "alta"
        assert stored["estado"] == "pendiente"
        assert stored["usuario_id"] == user_a.id
    finally:
        reopened.close()


def test_task_listing_is_owner_scoped_within_each_tenant(task_isolation_db):
    db, SessionLocal, _tables, user_a, user_a2, user_b = task_isolation_db
    task_a1 = create_task(TaskCreate(titulo="A1 private task"), user_a, db)
    task_a2 = create_task(TaskCreate(titulo="A2 private task"), user_a2, db)
    task_b = create_task(TaskCreate(titulo="B private task"), user_b, db)
    db.close()

    session = SessionLocal()
    try:
        rows_a1 = list_tasks(user_a, session)
        rows_a2 = list_tasks(user_a2, session)
        rows_b = list_tasks(user_b, session)

        assert [row["id"] for row in rows_a1] == [task_a1["id"]]
        assert [row["id"] for row in rows_a2] == [task_a2["id"]]
        assert [row["id"] for row in rows_b] == [task_b["id"]]
    finally:
        session.close()

def test_get_task_returns_not_found_for_missing_id_with_real_session(task_persistence_db):
    db, _SessionLocal, _tasks, user = task_persistence_db

    with pytest.raises(AppError) as error:
        get_task(uuid4(), user, db)

    assert error.value.status_code == 404
    assert error.value.detail == "Task not found"

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

def tenant_user(schema_name=SCHEMA_NAME):
    return SimpleNamespace(
        id=uuid4(),
        company_id=uuid4(),
        company=SimpleNamespace(is_active=True, schema_name=schema_name),
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
