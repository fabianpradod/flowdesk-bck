"""User updates and employee creation against a real SQLAlchemy session.

FakeDB applies attribute changes in place, so it cannot show what a failed request
leaves in the database. Here every failure is checked from a fresh session.
"""
from datetime import datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.companies import Company
from app.models.roles import Role
from app.models.users import User
from app.schemas.users import UserCreate, UserUpdate
from app.services import auth as auth_service
from app.services import users as users_service
from app.tenancy.runtime import get_tenant_tables
from app.utils.exceptions import AppError

CREATED = datetime(2026, 1, 1)
SCHEMA = "tenant_" + "a" * 32


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def attach_global(connection, _record):
        connection.execute("ATTACH DATABASE ':memory:' AS global")
        connection.execute(f"ATTACH DATABASE ':memory:' AS {SCHEMA}")
        # users.created_at defaults to Postgres now().
        connection.create_function("now", 0, lambda: CREATED.isoformat(" "))

    Base.metadata.create_all(engine, tables=[Role.__table__, Company.__table__, User.__table__])
    get_tenant_tables(SCHEMA)["audit_event"].create(engine)
    with Session(engine) as db:
        roles = {name: Role(name=name, description="", created_at=CREATED) for name in ("employee", "manager", "admin")}
        company = Company(name="Acme", schema_name="tenant_" + "a" * 32, is_active=True, created_at=CREATED)
        db.add_all([*roles.values(), company])
        db.flush()
        for username, role in (("admin", "admin"), ("employee", "employee")):
            db.add(User(
                username=username,
                email=f"{username}@example.com",
                password="x",
                role_id=roles[role].id,
                company_id=company.id,
                is_active=True,
                created_at=CREATED,
            ))
        db.commit()
    return engine


def _load(engine, username):
    with Session(engine) as db:
        user = db.query(User).filter(User.username == username).one()
        return {"id": user.id, "role": user.role.name, "is_active": user.is_active, "company_id": user.company_id}


def _role_id(engine, name):
    with Session(engine) as db:
        return db.query(Role).filter(Role.name == name).one().id


def _admin(db):
    return db.query(User).filter(User.username == "admin").one()


def _audit_rows(engine):
    with Session(engine) as db:
        return db.execute(select(get_tenant_tables(SCHEMA)["audit_event"])).mappings().all()


def test_update_applies_username_role_and_status_together(engine):
    employee = _load(engine, "employee")
    with Session(engine) as db:
        users_service.update_user(
            db,
            employee["id"],
            UserUpdate(username="promoted", role_id=_role_id(engine, "manager"), is_active=False),
            _admin(db),
        )

    stored = _load(engine, "promoted")
    assert stored["role"] == "manager"
    assert stored["is_active"] is False
    events = _audit_rows(engine)
    assert len(events) == 1
    assert events[0]["action"] == "user.role_changed"
    assert events[0]["entity_id"] == employee["id"]
    assert events[0]["actor_id"] == _load(engine, "admin")["id"]


def test_refused_update_leaves_every_field_unchanged(engine):
    employee = _load(engine, "employee")
    with Session(engine) as db:
        with pytest.raises(AppError) as exc:
            users_service.update_user(
                db,
                employee["id"],
                UserUpdate(username="must_not_apply", role_id=999999, is_active=False),
                _admin(db),
            )
        assert exc.value.status_code == 404
        db.commit()

    assert _load(engine, "employee") == employee


def test_username_taken_after_the_check_answers_400_and_changes_nothing(engine, monkeypatch):
    # Simulates another request committing the same username between the check
    # and this commit: the unique index is what refuses it.
    monkeypatch.setattr(users_service, "_assert_username_available", lambda _db, _username: None)
    employee = _load(engine, "employee")
    with Session(engine) as db:
        with pytest.raises(AppError) as exc:
            users_service.update_user(
                db,
                employee["id"],
                UserUpdate(username="admin", role_id=_role_id(engine, "manager"), is_active=False),
                _admin(db),
            )

    assert exc.value.status_code == 400
    assert exc.value.message == "Username already registered"
    assert _load(engine, "employee") == employee
    assert _audit_rows(engine) == []


def test_database_failure_on_update_answers_generic_error_and_changes_nothing(engine, monkeypatch):
    employee = _load(engine, "employee")
    with Session(engine) as db:
        def failing_commit():
            raise OperationalError("COMMIT", {}, Exception("connection lost"))

        monkeypatch.setattr(db, "commit", failing_commit)
        with pytest.raises(AppError) as exc:
            users_service.update_user(
                db,
                employee["id"],
                UserUpdate(role_id=_role_id(engine, "manager"), is_active=False),
                _admin(db),
            )

    assert exc.value.status_code == 500
    assert exc.value.message == "Failed to update user"
    assert _load(engine, "employee") == employee
    assert _audit_rows(engine) == []


def test_audit_failure_rolls_back_all_employee_changes(engine, monkeypatch):
    employee = _load(engine, "employee")

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError("audit storage unavailable")

    monkeypatch.setattr(users_service, "record_event", fail_audit)
    with Session(engine) as db:
        with pytest.raises(AppError) as exc:
            users_service.update_user(
                db,
                employee["id"],
                UserUpdate(username="must_not_apply", role_id=_role_id(engine, "manager"), is_active=False),
                _admin(db),
            )
        assert exc.value.status_code == 500
        db.commit()

    assert _load(engine, "employee") == employee
    assert _audit_rows(engine) == []


@pytest.mark.parametrize(
    ("email", "username", "message"),
    [
        ("employee@example.com", "fresh_user", "Email already registered"),
        ("fresh@example.com", "employee", "Username already registered"),
    ],
)
def test_employee_registered_after_the_check_answers_400(engine, monkeypatch, email, username, message):
    checks = []

    def check_once_free(db, check_email, check_username):
        # The first call is the pre-check, which the concurrent request passed
        # too. The second runs after the unique index refused the insert.
        checks.append(check_email)
        if len(checks) > 1:
            original_check(db, check_email, check_username)

    original_check = auth_service._assert_employee_identity_available
    monkeypatch.setattr(auth_service, "_assert_employee_identity_available", check_once_free)
    monkeypatch.setattr(auth_service, "send_password_set_email", lambda *_args: pytest.fail("no email on failure"))

    with Session(engine) as db:
        with pytest.raises(AppError) as exc:
            auth_service.create_employee(
                UserCreate(username=username, email=email, role_id=_role_id(engine, "employee")),
                _admin(db),
                db,
            )

    assert exc.value.status_code == 400
    assert exc.value.message == message
    with Session(engine) as db:
        assert db.query(User).count() == 2


@pytest.mark.parametrize("username", ["", "   ", "x" * 51])
def test_user_payloads_reject_blank_or_oversized_usernames(username):
    with pytest.raises(ValidationError):
        UserUpdate(username=username)
    with pytest.raises(ValidationError):
        UserCreate(username=username, email="new@example.com", role_id=1)


def test_user_payloads_trim_usernames():
    assert UserUpdate(username="  bob  ").username == "bob"
    assert UserCreate(username="  bob  ", email="bob@example.com", role_id=1).username == "bob"
