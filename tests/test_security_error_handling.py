"""Error responses must not expose exceptions or internal information.

Every failure should reach the client in the same JSON contract,
{"message", "code", "errors"}, with a message written for the client: no SQL, no
schema names, no tracebacks, no echo of what was submitted.
"""

import ast
import logging
import pathlib
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.sql import Select

from app.api.dependencies.auth import get_db
from app.models.users import User
from main import app
from tests.security_helpers import FakeQuery, FakeResult, client_for, make_company, make_user

INTERNAL_MARKERS = (
    "SELECT",
    "UPDATE ",
    "INSERT",
    "tenant_",
    "Traceback",
    "psycopg2",
    "sqlalchemy",
    "OperationalError",
    'File "',
)


def assert_clean_error(response, status):
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert set(body) == {"message", "code", "errors"}
    for marker in INTERNAL_MARKERS:
        assert marker not in response.text, marker
    return body


# Validation errors

INVALID_REQUESTS = [
    ("manager", "POST", "/api/v1/inventory/movements",
     {"producto_id": str(uuid4()), "tipo_movimiento": "entrada_manual", "cantidad": 0}),
    ("manager", "POST", "/api/v1/inventory/products", {"sku": "a", "nombre": "b", "precio_venta": -1}),
    ("manager", "POST", "/api/v1/commercial/sales",
     {"items": [{"producto_id": str(uuid4()), "cantidad": "0"}]}),
    ("employee", "PUT", f"/api/v1/tasks/{uuid4()}", {}),
    ("admin", "GET", "/api/v1/inventory/suppliers/not-a-uuid", None),
    ("manager", "GET", "/api/v1/inventory/analytics/trend?window=year", None),
    ("admin", "POST", "/api/v1/auth/employees", {"username": "x", "email": "no-es-correo", "role_id": 4}),
]


@pytest.mark.parametrize(
    "role, method, path, body", INVALID_REQUESTS, ids=[f"{c[1]} {c[2]}" for c in INVALID_REQUESTS]
)
def test_invalid_input_is_a_clean_422(role, method, path, body):
    """Limits held as Decimal, or a validator's ValueError, used to crash the
    handler into a text/plain 500."""
    response = client_for(make_user(role, make_company())).request(method, path, json=body)

    payload = assert_clean_error(response, 422)
    assert payload["code"] == "validation_error"
    assert payload["errors"]
    for error in payload["errors"]:
        assert set(error) == {"loc", "msg", "type"}


@pytest.mark.parametrize("path, body", [
    ("/api/v1/auth/login", {"password": "S3cret-Value!"}),
    ("/api/v1/auth/password/reset", {"new_password": "S3cret-Value!"}),
    ("/api/v1/auth/password/set", {"new_password": "S3cret-Value!"}),
])
def test_a_validation_error_does_not_echo_the_password(client, path, body):
    response = client.post(path, json=body)

    assert_clean_error(response, 422)
    assert "S3cret-Value!" not in response.text


# Unexpected failures

def test_an_unexpected_exception_becomes_a_generic_500(monkeypatch):
    def explode(*_args, **_kwargs):
        raise RuntimeError("boom in tenant_0123 while running SELECT * FROM secrets")

    monkeypatch.setattr("app.services.inventory.list_products", explode)

    response = client_for(make_user("employee", make_company())).get("/api/v1/inventory/products")

    body = assert_clean_error(response, 500)
    assert body == {"message": "Internal server error", "code": "internal_error", "errors": []}
    assert "boom" not in response.text


# Database failures

def _db_error():
    return OperationalError(
        "UPDATE tenant_0123456789abcdef0123456789abcdef.proveedor SET nombre=%(nombre)s",
        {"nombre": "secret-parameter"},
        Exception("server closed the connection unexpectedly"),
    )


def _row(**overrides):
    row = {
        "id": uuid4(),
        "nombre": "Acme",
        "is_active": True,
        "sku": "sku-1",
        "stock_actual": Decimal("10"),
        "stock_minimo": Decimal("0"),
        "precio_venta": Decimal("1"),
    }
    row.update(overrides)
    return row


class FailingWritesDB:
    """Answers each SELECT with the next prepared list of rows and fails every
    write the way a dropped connection would."""

    def __init__(self, *select_rows):
        self.select_rows = list(select_rows)
        self.rollbacks = 0

    def execute(self, statement, *_args, **_kwargs):
        if isinstance(statement, Select):
            return FakeResult(self.select_rows.pop(0) if self.select_rows else [])
        raise _db_error()

    def query(self, _model):
        return FakeQuery()

    def commit(self):
        pass

    def rollback(self):
        self.rollbacks += 1


DB_FAILURES = [
    ("PUT", "/api/v1/inventory/suppliers/{id}", {"telefono": "555"}, [[_row()]], "Failed to update supplier"),
    ("PATCH", "/api/v1/inventory/suppliers/{id}/status", {"is_active": False}, [[_row()], []],
     "Failed to update supplier status"),
    ("DELETE", "/api/v1/inventory/suppliers/{id}", None, [[_row()], []], "Failed to update supplier status"),
    ("PATCH", "/api/v1/inventory/products/{id}/status", {"is_active": False}, [[_row()]],
     "Failed to update product status"),
    ("POST", "/api/v1/inventory/movements",
     {"producto_id": str(uuid4()), "tipo_movimiento": "entrada_manual", "cantidad": "1"}, [[_row()]],
     "Inventory movement failed"),
]


@pytest.mark.parametrize(
    "method, path, body, selects, message", DB_FAILURES, ids=[f"{c[0]} {c[1]}" for c in DB_FAILURES]
)
def test_a_database_failure_does_not_reach_the_client(method, path, body, selects, message):
    """These returned str(e): the SQL, the tenant schema and the parameters."""
    db = FailingWritesDB(*selects)
    session = client_for(make_user("admin", make_company()), db)

    response = session.request(method, path.format(id=uuid4()), json=body)

    payload = assert_clean_error(response, 500)
    assert payload["message"] == message
    assert "secret-parameter" not in response.text
    assert db.rollbacks == 1


def test_a_database_failure_is_still_logged_for_the_operators(caplog):
    db = FailingWritesDB([_row()])
    session = client_for(make_user("admin", make_company()), db)

    with caplog.at_level(logging.ERROR, logger="flowdesk"):
        session.patch(f"/api/v1/inventory/products/{uuid4()}/status", json={"is_active": False})

    assert any(record.exc_info for record in caplog.records)


def _formats_the_caught_exception(handler: ast.ExceptHandler) -> list[int]:
    lines = []
    for node in ast.walk(handler):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "AppError":
            for part in ast.walk(node):
                if isinstance(part, ast.Name) and part.id == handler.name:
                    lines.append(node.lineno)
    return lines


def test_no_service_puts_a_caught_exception_into_an_error_message():
    """Covers the supplier product services too, which have no route yet."""
    offenders = []
    for path in sorted(pathlib.Path("app").rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler) and node.name:
                offenders += [f"{path}:{line}" for line in _formats_the_caught_exception(node)]

    assert not offenders, offenders


# Specific cases

class BrokenDB:
    def execute(self, *_args, **_kwargs):
        raise _db_error()


def test_readiness_answers_503_when_the_database_is_down():
    app.dependency_overrides[get_db] = lambda: BrokenDB()

    response = TestClient(app, raise_server_exceptions=False).get("/ready")

    body = assert_clean_error(response, 503)
    assert body["message"] == "Database is not ready"


def _seeded(email):
    return next(user for user in app.state.test_db.data[User] if user.email == email)


def test_renaming_a_user_to_a_taken_username_is_a_400(admin_client):
    """The unique index caught it first, as a 500."""
    employee = _seeded("employee.demo@flowdesk.com")

    response = admin_client.put(f"/api/v1/users/{employee.id}", json={"username": "demo_manager"})

    body = assert_clean_error(response, 400)
    assert body["message"] == "Username already registered"
    assert employee.username == "demo_employee"


def test_keeping_the_same_username_is_not_a_conflict(admin_client):
    employee = _seeded("employee.demo@flowdesk.com")

    response = admin_client.put(f"/api/v1/users/{employee.id}", json={"username": "demo_employee"})

    assert response.status_code == 200


def test_an_email_failure_is_logged_without_the_address(admin_client, monkeypatch, caplog, capsys):
    def fail(*_args, **_kwargs):
        raise ConnectionError("smtp down")

    monkeypatch.setattr("app.services.auth.send_password_set_email", fail)

    with caplog.at_level(logging.WARNING, logger="flowdesk"):
        response = admin_client.post(
            "/api/v1/auth/employees",
            json={"username": "nuevo", "email": "nuevo.empleado@test.com", "role_id": 4},
        )

    assert response.status_code == 201
    assert caplog.records
    assert "nuevo.empleado@test.com" not in caplog.text
    assert "nuevo.empleado@test.com" not in capsys.readouterr().out
