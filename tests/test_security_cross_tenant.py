"""Negative scenarios with identifiers that belong to another company.

Tenant records: company B's ids are sent by a company A user in every place an id
is accepted (path, body, filter). Since every statement names A's schema, B's
record cannot be found: the answer is a 404 or an empty result, never B's data and
never a 500.

Global records (users): they share one table, so the services filter by company.
A B user must look exactly like a user that does not exist.
"""

from uuid import uuid4

import pytest

from app.models.users import User
from main import app
from tests.security_helpers import (
    RecordingDB,
    add_company_with_users,
    call,
    client_for,
    make_company,
    make_user,
    request_kwargs,
    schemas_in,
)

# Tenant ids

NOT_FOUND = {
    ("GET", "/api/v1/inventory/suppliers/{supplier_id}"): "Supplier not found",
    ("PUT", "/api/v1/inventory/suppliers/{supplier_id}"): "Supplier not found",
    ("PATCH", "/api/v1/inventory/suppliers/{supplier_id}/status"): "Supplier not found",
    ("DELETE", "/api/v1/inventory/suppliers/{supplier_id}"): "Supplier not found",
    ("PATCH", "/api/v1/inventory/products/{product_id}/status"): "Product not found",
    ("POST", "/api/v1/inventory/products"): "Supplier not found",
    ("POST", "/api/v1/inventory/movements"): "Product not found",
    ("GET", "/api/v1/commercial/clients/{client_id}"): "Client not found",
    ("PUT", "/api/v1/commercial/clients/{client_id}"): "Client not found",
    ("PATCH", "/api/v1/commercial/clients/{client_id}/status"): "Client not found",
    ("DELETE", "/api/v1/commercial/clients/{client_id}"): "Client not found",
    ("GET", "/api/v1/commercial/clients/{client_id}/purchases"): "Client not found",
    ("POST", "/api/v1/commercial/sales"): "Client not found",
    ("GET", "/api/v1/commercial/sales/{sale_id}"): "Sale not found",
    ("GET", "/api/v1/tasks/{task_id}"): "Task not found",
    ("PUT", "/api/v1/tasks/{task_id}"): "Task not found",
    ("PATCH", "/api/v1/tasks/{task_id}/status"): "Task not found",
    ("DELETE", "/api/v1/tasks/{task_id}"): "Task not found",
}

FILTERS = {
    "/api/v1/inventory/movements": {"product_id"},
    "/api/v1/inventory/history": {"product_id"},
    "/api/v1/inventory/supplier-products": {"product_id", "supplier_id"},
}


def _as_company_a(role="admin"):
    company_a = make_company(name="A")
    db = RecordingDB()
    return client_for(make_user(role, company_a), db), db, company_a


@pytest.mark.parametrize("key", sorted(NOT_FOUND), ids=lambda key: f"{key[0]} {key[1]}")
def test_another_companys_id_is_not_found(key):
    session, db, company_a = _as_company_a()
    foreign_id = uuid4()

    response = call(session, key, foreign_id, **request_kwargs(key, foreign_id))

    assert response.status_code == 404, response.text
    assert response.json()["message"] == NOT_FOUND[key]
    assert schemas_in(db.statements) == {company_a.schema_name}


def test_a_sale_of_another_companys_product_is_not_found():
    session, db, company_a = _as_company_a()

    response = session.post(
        "/api/v1/commercial/sales",
        json={"items": [{"producto_id": str(uuid4()), "cantidad": "1"}]},
    )

    assert response.status_code == 404
    assert response.json()["message"].startswith("Product not found")
    assert schemas_in(db.statements) == {company_a.schema_name}


def test_importing_products_for_another_companys_supplier_is_refused():
    session, db, company_a = _as_company_a()
    csv = f"sku,nombre,proveedor_id\nsku-1,Prod,{uuid4()}\n".encode()

    response = session.post(
        "/api/v1/inventory/products/import",
        files={"file": ("productos.csv", csv, "text/csv")},
    )

    assert response.status_code == 400
    assert response.json()["errors"][0]["code"] == "supplier_not_found"
    assert schemas_in(db.statements) == {company_a.schema_name}


@pytest.mark.parametrize("path, param", [
    (path, param) for path, params in FILTERS.items() for param in sorted(params)
])
def test_filtering_by_another_companys_id_returns_nothing(path, param):
    session, db, company_a = _as_company_a()

    response = session.get(path, params={param: str(uuid4())})

    assert response.status_code == 200
    assert response.json() == []
    assert schemas_in(db.statements) == {company_a.schema_name}


# Global ids: users

@pytest.fixture
def company_b():
    return add_company_with_users(app.state.test_db, "admin", "employee")


def _employee_of(company_b):
    return company_b[1][1]


USER_ROUTES = [
    ("PUT", "/api/v1/users/{user_id}", {"username": "tomado"}),
    ("PATCH", "/api/v1/users/{user_id}/status", {"is_active": False}),
    ("DELETE", "/api/v1/users/{user_id}", None),
]


@pytest.mark.parametrize("method, path, body", USER_ROUTES)
def test_another_companys_user_is_not_found(admin_client, company_b, method, path, body):
    target = _employee_of(company_b)

    response = admin_client.request(method, path.format(user_id=target.id), json=body)

    assert response.status_code == 404
    assert response.json()["message"] == "User not found"
    assert target.username == "otra_employee"
    assert target.is_active is True


@pytest.mark.parametrize("method, path, body", USER_ROUTES)
def test_another_companys_user_looks_exactly_like_a_missing_one(admin_client, company_b, method, path, body):
    """Any difference between the two answers tells an admin the id exists."""
    foreign = admin_client.request(method, path.format(user_id=_employee_of(company_b).id), json=body)
    missing = admin_client.request(method, path.format(user_id=uuid4()), json=body)

    assert (foreign.status_code, foreign.json()) == (missing.status_code, missing.json())


def test_superadmin_still_manages_users_of_any_company(superadmin_client, company_b):
    target = _employee_of(company_b)

    response = superadmin_client.put(f"/api/v1/users/{target.id}", json={"username": "movido"})

    assert response.status_code == 200
    assert target.username == "movido"


@pytest.fixture
def sent_invitations(monkeypatch):
    sent = []
    monkeypatch.setattr(
        "app.services.auth.send_password_set_email", lambda email, _token: sent.append(email)
    )
    return sent


@pytest.mark.parametrize("pending", [False, True], ids=["active", "pending"])
def test_resending_an_invitation_to_another_companys_user_is_not_found(
    admin_client, company_b, sent_invitations, pending
):
    """The status used to be checked first, so an active user of another company
    answered 400 'already active' and a missing one 404."""
    target = _employee_of(company_b)
    if pending:
        target.is_active, target.password = False, ""

    foreign = admin_client.post("/api/v1/auth/invitations/resend", json={"email": target.email})
    missing = admin_client.post("/api/v1/auth/invitations/resend", json={"email": "nadie@otra.com"})

    assert foreign.status_code == 404
    assert foreign.json() == missing.json()
    assert sent_invitations == []


def test_an_email_taken_in_another_company_is_refused_cleanly(admin_client, company_b):
    """Emails are unique across companies (login looks users up by email alone).
    The check only looked inside the admin's company, so the insert hit the
    unique index and answered 500."""
    taken = _employee_of(company_b).email
    before = len(app.state.test_db.data[User])

    response = admin_client.post(
        "/api/v1/auth/employees",
        json={"username": "duplicado", "email": taken, "role_id": 4},
    )

    assert response.status_code == 400
    assert response.json()["message"] == "Email already registered"
    assert len(app.state.test_db.data[User]) == before
