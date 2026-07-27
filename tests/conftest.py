import importlib
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
import app.services.auth as auth_service
from app.api.dependencies.auth import get_current_user, get_db
from app.core.config import DEMO_USER_PASSWORD
from app.core.security import hash_password
from app.db import init_db as init_db_module
from app.models.companies import Company
from app.models.roles import Role
from app.models.users import User
from app.tenancy.bootstrap import generate_schema_name

def _ensure_defaults(obj):
    if getattr(obj, "id", None) is None:
        obj.id = uuid4()

    if getattr(obj, "created_at", None) is None:
        obj.created_at = datetime.now(timezone.utc)

    if isinstance(obj, Company) and getattr(obj, "is_active", None) is None:
        obj.is_active = True

    if isinstance(obj, User) and getattr(obj, "is_active", None) is None:
        obj.is_active = False

    return obj

class FakeQuery:
    def __init__(self, db, model):
        self.db = db
        self.model = model
        self.criteria = []

    def filter(self, *criteria, **_kwargs):
        self.criteria.extend(criteria)
        return self

    def join(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def _matches(self, obj) -> bool:
        for expr in self.criteria:
            if not _matches_expression(obj, expr):
                return False
        return True

    def all(self):
        items = list(self.db.data.get(self.model, []))
        return [item for item in items if self._matches(item)]

    def first(self):
        rows = self.all()
        return rows[0] if rows else None

class FakeDB:
    def __init__(self, data=None):
        self.data = data or {}
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.refreshed = []
        self.connection_obj = object()

    def query(self, model):
        return FakeQuery(self, model)

    def add(self, obj):
        _ensure_defaults(obj)
        self.added.append(obj)
        self.data.setdefault(obj.__class__, []).append(obj)

    def flush(self):
        for obj in self.added:
            _ensure_defaults(obj)

    def refresh(self, obj):
        _ensure_defaults(obj)
        self.refreshed.append(obj)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def connection(self):
        return self.connection_obj

def _matches_expression(obj, expr) -> bool:
    left = getattr(expr, "left", None)
    right = getattr(expr, "right", None)

    if left is None or right is None:
        return True

    attr_name = getattr(left, "key", None) or getattr(left, "name", None)
    expected = getattr(right, "value", right)
    actual = getattr(obj, attr_name, None)

    if actual == expected:
        return True

    return str(actual) == str(expected)

def _seed_fake_db() -> FakeDB:
    now = datetime.now(timezone.utc)

    company_id = uuid4()
    company = Company(
        name="Flowdesk Demo",
        schema_name=generate_schema_name(company_id),
        is_active=True,
    )
    company.id = company_id
    company.created_at = now

    superadmin_role = Role(
        name="superadmin",
        description="Full access to all resources and settings.",
    )
    superadmin_role.id = 1
    superadmin_role.created_at = now

    admin_role = Role(
        name="admin",
        description="Manage inventory, sales, and users within their company.",
    )
    admin_role.id = 2
    admin_role.created_at = now

    manager_role = Role(
        name="manager",
        description="Manage inventory and sales, but cannot manage users.",
    )
    manager_role.id = 3
    manager_role.created_at = now

    employee_role = Role(
        name="employee",
        description="View inventory and sales, but cannot make changes.",
    )
    employee_role.id = 4
    employee_role.created_at = now

    superadmin = User(
        username="superadmin",
        email="superadmin@test.com",
        password=hash_password(DEMO_USER_PASSWORD),
        role_id=superadmin_role.id,
        company_id=None,
        is_active=True,
    )
    superadmin.id = uuid4()
    superadmin.created_at = now
    superadmin.role = superadmin_role
    superadmin.company = None

    admin = User(
        username="demo_admin",
        email="admin.demo@flowdesk.com",
        password=hash_password(DEMO_USER_PASSWORD),
        role_id=admin_role.id,
        company_id=company.id,
        is_active=True,
    )
    admin.id = uuid4()
    admin.created_at = now
    admin.role = admin_role
    admin.company = company

    manager = User(
        username="demo_manager",
        email="manager.demo@flowdesk.com",
        password=hash_password(DEMO_USER_PASSWORD),
        role_id=manager_role.id,
        company_id=company.id,
        is_active=True,
    )
    manager.id = uuid4()
    manager.created_at = now
    manager.role = manager_role
    manager.company = company

    employee = User(
        username="demo_employee",
        email="employee.demo@flowdesk.com",
        password=hash_password(DEMO_USER_PASSWORD),
        role_id=employee_role.id,
        company_id=company.id,
        is_active=True,
    )
    employee.id = uuid4()
    employee.created_at = now
    employee.role = employee_role
    employee.company = company

    inactive_user = User(
        username="inactive_user",
        email="inactive@test.com",
        password=hash_password(DEMO_USER_PASSWORD),
        role_id=employee_role.id,
        company_id=company.id,
        is_active=False,
    )
    inactive_user.id = uuid4()
    inactive_user.created_at = now
    inactive_user.role = employee_role
    inactive_user.company = company

    return FakeDB(
        data={
            Company: [company],
            Role: [superadmin_role, admin_role, manager_role, employee_role],
            User: [superadmin, admin, manager, employee, inactive_user],
        }
    )

def _seeded_user_by_email(email: str):
    db = app.state.test_db
    for user in db.data.get(User, []):
        if user.email == email:
            return user
    raise AssertionError(f"Seeded user not found: {email}")

with patch.object(init_db_module, "init_db", return_value=None):
    main_module = importlib.import_module("main")
    sys.modules["main"] = main_module

app = main_module.app

@pytest.fixture(autouse=True)
def reset_dependency_overrides():
    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = lambda: app.state.test_db
    yield
    app.dependency_overrides.clear()
    app.dependency_overrides[get_db] = lambda: app.state.test_db

app.dependency_overrides[get_db] = lambda: app.state.test_db

@pytest.fixture(autouse=True)
def clear_rate_limit():
    auth_service._reset_attempts.clear()
    yield
    auth_service._reset_attempts.clear()

@pytest.fixture(autouse=True)
def seed_test_db():
    app.state.test_db = _seed_fake_db()
    yield
    app.state.test_db = _seed_fake_db()

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def admin_client():
    app.dependency_overrides[get_current_user] = lambda: _seeded_user_by_email(
        "admin.demo@flowdesk.com"
    )
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)

@pytest.fixture
def superadmin_client():
    app.dependency_overrides[get_current_user] = lambda: _seeded_user_by_email(
        "superadmin@test.com"
    )
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)

@pytest.fixture
def employee_client():
    app.dependency_overrides[get_current_user] = lambda: _seeded_user_by_email(
        "employee.demo@flowdesk.com"
    )
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)

@pytest.fixture(autouse=True)
def mute_external_side_effects(monkeypatch):
    monkeypatch.setattr(
        "app.services.auth.bootstrap_tenant_schema",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.auth.send_password_set_email",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        "app.services.auth.send_password_reset_email",
        lambda *args, **kwargs: None,
    )