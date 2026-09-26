"""Operations attempted by roles that must not have access.

Two layers. The route guard: every role below a route's minimum is refused before
the request touches the database. The services: escalation attempts that pass the
guard legitimately (an admin is allowed on /users) but try to reach further than
the role allows.
"""

from datetime import timedelta
from uuid import uuid4

import pytest

from app.core.security import create_access_token
from app.models.users import User
from main import app
from tests.security_helpers import (
    ADMIN,
    ALLOWED_ROLES,
    GUARD_REFUSAL,
    MANAGER,
    ROLES,
    ROUTE_POLICY,
    SUPERADMIN_STRICT,
    RecordingDB,
    call,
    client_for,
    make_company,
    make_user,
    protected_routes,
)

REFUSED = [
    (key, role)
    for key in protected_routes()
    for role in ROLES
    if role not in ALLOWED_ROLES[ROUTE_POLICY[key]]
]

ROLE_RESTRICTED = [
    key for key in protected_routes() if ROUTE_POLICY[key] in {MANAGER, ADMIN, SUPERADMIN_STRICT}
]


def _case_id(case):
    (method, path), role = case
    return f"{role} {method} {path}"


# Route guard

@pytest.mark.parametrize("case", REFUSED, ids=[_case_id(case) for case in REFUSED])
def test_role_below_the_minimum_is_refused_before_any_data_access(case):
    key, role = case
    db = RecordingDB()

    response = call(client_for(make_user(role), db), key)

    assert response.status_code == 403, response.text
    assert response.json()["message"] == GUARD_REFUSAL
    assert not db.touched


@pytest.mark.parametrize("key", ROLE_RESTRICTED, ids=lambda key: f"{key[0]} {key[1]}")
def test_a_user_without_a_role_is_refused_on_role_restricted_routes(key):
    db = RecordingDB()
    user = make_user("employee")
    user.role = None

    response = call(client_for(user, db), key)

    assert response.status_code == 403
    assert not db.touched


def test_every_role_but_superadmin_is_refused_somewhere():
    assert {role for _key, role in REFUSED} == {"employee", "manager", "admin"}


# Escalation through the user administration endpoints

def _seeded(email):
    return next(user for user in app.state.test_db.data[User] if user.email == email)


SUPERADMIN_ROLE_ID = 1
EMPLOYEE_ROLE_ID = 4


def test_admin_cannot_promote_a_user_to_superadmin(admin_client):
    employee = _seeded("employee.demo@flowdesk.com")

    response = admin_client.put(
        f"/api/v1/users/{employee.id}", json={"role_id": SUPERADMIN_ROLE_ID}
    )

    assert response.status_code == 403
    assert employee.role_id == EMPLOYEE_ROLE_ID


def test_admin_cannot_create_a_superadmin_through_the_employees_endpoint(admin_client):
    before = len(app.state.test_db.data[User])

    response = admin_client.post(
        "/api/v1/auth/employees",
        json={"username": "sneaky", "email": "sneaky@test.com", "role_id": SUPERADMIN_ROLE_ID},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_employee_role"
    assert len(app.state.test_db.data[User]) == before


@pytest.mark.parametrize("method, suffix, body", [
    ("PUT", "", {"username": "taken_over"}),
    ("PATCH", "/status", {"is_active": False}),
    ("DELETE", "", None),
])
def test_admin_cannot_touch_the_superadmin(admin_client, method, suffix, body):
    superadmin = _seeded("superadmin@test.com")

    response = admin_client.request(
        method, f"/api/v1/users/{superadmin.id}{suffix}", json=body
    )

    assert response.status_code in (403, 404)
    assert superadmin.username == "superadmin"
    assert superadmin.is_active is True


def test_admin_cannot_place_an_employee_in_another_company(admin_client):
    admin = _seeded("admin.demo@flowdesk.com")

    response = admin_client.post(
        "/api/v1/auth/employees",
        json={
            "username": "planted",
            "email": "planted@test.com",
            "role_id": EMPLOYEE_ROLE_ID,
            "company_id": str(uuid4()),
        },
    )

    assert response.status_code == 201
    assert response.json()["company_id"] == str(admin.company_id)


def test_admin_cannot_change_their_own_status(admin_client):
    """Only DELETE blocked it: PATCH let an admin lock themselves out."""
    admin = _seeded("admin.demo@flowdesk.com")

    response = admin_client.patch(f"/api/v1/users/{admin.id}/status", json={"is_active": False})

    assert response.status_code == 400
    assert admin.is_active is True


def test_admin_cannot_delete_their_own_account(admin_client):
    admin = _seeded("admin.demo@flowdesk.com")

    response = admin_client.delete(f"/api/v1/users/{admin.id}")

    assert response.status_code == 400
    assert admin.is_active is True


# Invitation links

def _invitation_for(user):
    return create_access_token(
        {"sub": str(user.id), "purpose": "set_password"}, expires_delta=timedelta(hours=48)
    )


def test_an_old_invitation_cannot_reactivate_a_deactivated_account(client):
    """A deactivated user keeps their password hash, a pending one has none."""
    deactivated = _seeded("inactive@test.com")
    password_before = deactivated.password

    response = client.post(
        "/api/v1/auth/password/set",
        json={"token": _invitation_for(deactivated), "new_password": "BackAgain123!"},
    )

    assert response.status_code == 400
    assert deactivated.is_active is False
    assert deactivated.password == password_before


def test_an_invitation_can_only_be_used_once(client):
    pending = _seeded("inactive@test.com")
    pending.password = ""
    token = _invitation_for(pending)

    first = client.post("/api/v1/auth/password/set", json={"token": token, "new_password": "First123!"})
    second = client.post("/api/v1/auth/password/set", json={"token": token, "new_password": "Second123!"})

    assert first.status_code == 200
    assert second.status_code == 400


def test_an_invitation_cannot_overwrite_an_active_users_password(client):
    admin = _seeded("admin.demo@flowdesk.com")
    password_before = admin.password

    response = client.post(
        "/api/v1/auth/password/set",
        json={"token": _invitation_for(admin), "new_password": "Hijacked123!"},
    )

    assert response.status_code == 400
    assert admin.password == password_before


# Tasks: every role may use them, but only on its own records

TASK_ROUTES = [key for key in protected_routes() if key[1].startswith("/api/v1/tasks")]


@pytest.mark.parametrize("key", TASK_ROUTES, ids=lambda key: f"{key[0]} {key[1]}")
def test_every_task_statement_is_scoped_to_the_caller(key):
    db = RecordingDB()
    user = make_user("employee", make_company())
    body = {"titulo": "x", "estado": "completada"} if key[0] in {"POST", "PUT", "PATCH"} else None

    call(client_for(user, db), key, json=body)

    assert db.statements, "the route never queried the tasks table"
    for statement in db.statements:
        assert user.id in statement.compile().params.values(), str(statement)


def test_an_employee_cannot_create_a_task_for_someone_else():
    db = RecordingDB()
    user = make_user("employee", make_company())
    someone_else = uuid4()

    call(
        client_for(user, db),
        ("POST", "/api/v1/tasks"),
        json={"titulo": "x", "usuario_id": str(someone_else)},
    )

    insert = db.statements[0]
    params = insert.compile().params
    assert params["usuario_id"] == user.id
    assert someone_else not in params.values()
