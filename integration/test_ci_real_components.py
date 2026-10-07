"""HTTP integration against a running API and disposable PostgreSQL.

Kept outside tests/ to avoid that suite's automatic FakeDB overrides.
Run explicitly with `python -m pytest integration -v` after starting the API.
No production database or third-party mail/AI credentials are required.
"""
import os
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import select

from app.core.database import get_engine
from app.models.companies import Company
from app.models.roles import Role
from app.models.users import User
from app.tenancy.runtime import get_tenant_tables


@pytest.fixture
def api():
    with httpx.Client(base_url=os.getenv("CI_API_URL", "http://127.0.0.1:8000"), timeout=10) as client:
        yield client


def login(api, email="admin.demo@flowdesk.com"):
    response = api.post("/api/v1/auth/login", json={
        "email": email,
        "password": os.environ["DEMO_USER_PASSWORD"],
    })
    assert response.status_code == 200, response.text
    assert response.json()["token_type"] == "bearer"
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_readiness_checks_real_postgres(api):
    """HTTP router -> DB dependency -> actual PostgreSQL SELECT 1."""
    response = api.get("/ready")
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ready"}
    with get_engine().connect() as conn:
        assert conn.execute(select(Company.id).where(Company.name == "Flowdesk Demo")).first()


def test_persisted_user_login_and_protected_roles(api):
    """Stored password -> authentication -> JWT -> protected role query."""
    headers = login(api)
    response = api.get("/api/v1/roles", headers=headers)
    assert response.status_code == 200, response.text
    assert {role["name"] for role in response.json()} == {"superadmin", "admin", "manager", "employee"}
    with get_engine().connect() as conn:
        assert set(conn.execute(select(Role.name)).scalars()) == {role["name"] for role in response.json()}
    assert api.get("/api/v1/roles").status_code == 401


def test_task_lifecycle_is_persisted_and_owned(api):
    """HTTP -> JWT -> tenant task service -> SQLAlchemy -> PostgreSQL."""
    headers = login(api)
    other_headers = login(api, "employee.demo@flowdesk.com")
    title = f"CI task {uuid4().hex}"
    created = api.post("/api/v1/tasks", headers=headers, json={"titulo": title, "prioridad": "alta"})
    assert created.status_code == 201, created.text
    task_id = UUID(created.json()["id"])
    with get_engine().connect() as conn:
        schema = conn.execute(select(Company.schema_name).where(Company.name == "Flowdesk Demo")).scalar_one()
        owner = conn.execute(select(User.id).where(User.email == "admin.demo@flowdesk.com")).scalar_one()
    tasks = get_tenant_tables(schema)["tarea"]
    try:
        with get_engine().connect() as conn:
            row = conn.execute(select(tasks).where(tasks.c.id == task_id)).mappings().one()
            assert row["titulo"] == title
            assert row["usuario_id"] == owner
            assert row["estado"] == "pendiente"
        fetched = api.get(f"/api/v1/tasks/{task_id}", headers=headers)
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["titulo"] == title
        assert api.get(f"/api/v1/tasks/{task_id}", headers=other_headers).status_code == 404
        updated = api.patch(f"/api/v1/tasks/{task_id}/status", headers=headers, json={"estado": "completada"})
        assert updated.status_code == 200, updated.text
        with get_engine().connect() as conn:
            assert conn.execute(select(tasks.c.estado).where(tasks.c.id == task_id)).scalar_one() == "completada"
    finally:
        deleted = api.delete(f"/api/v1/tasks/{task_id}", headers=headers)
        assert deleted.status_code == 204, deleted.text
    with get_engine().connect() as conn:
        assert conn.execute(select(tasks.c.id).where(tasks.c.id == task_id)).first() is None
