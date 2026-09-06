"""Authorization coverage for the permission matrix documented in the README.

Each case drives the real router through TestClient with a stubbed database, so
what is under test is the guard on the route, not a service called directly.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.dependencies.auth import get_current_user, get_db
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.commercial import router as commercial_router
from app.api.v1.routes.companies import router as companies_router
from app.api.v1.routes.inventory import router as inventory_router
from app.api.v1.routes.roles import router as roles_router
from app.api.v1.routes.users import router as users_router
from app.utils.exceptions import build_error_payload

SCHEMA_NAME = "tenant_" + "a" * 32

ROLES = ("employee", "manager", "admin", "superadmin")


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def one(self):
        return self.rows[0]

    def all(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


class FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def order_by(self, *_args):
        return self

    def filter(self, *_args):
        return self

    def join(self, *_args):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class FakeDB:
    """Answers anything with an empty result, so only the guard decides."""

    def __init__(self):
        self.executed = 0

    def execute(self, _statement):
        self.executed += 1
        return FakeResult([])

    def query(self, _model):
        return FakeQuery([])

    def commit(self):
        pass

    def rollback(self):
        pass


def user_with_role(role_name):
    company = SimpleNamespace(is_active=True, schema_name=SCHEMA_NAME, name="Acme")
    return SimpleNamespace(
        id=uuid4(),
        username=role_name,
        email=f"{role_name}@test.com",
        company_id=uuid4(),
        company=company,
        is_active=True,
        role=SimpleNamespace(name=role_name),
    )


def build_app(*routers):
    """A minimal app carrying the same error handler main.py installs, so the
    response body matches production rather than Starlette's default."""
    app = FastAPI()
    for router in routers or (commercial_router,):
        app.include_router(router)

    @app.exception_handler(StarletteHTTPException)
    async def _handler(_request: Request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content=build_error_payload(exc))

    app.dependency_overrides[get_db] = lambda: FakeDB()
    return app


def client_as(role_name, *routers):
    app = build_app(*routers)
    app.dependency_overrides[get_current_user] = lambda: user_with_role(role_name)
    return TestClient(app, raise_server_exceptions=False)


def anonymous_client(*routers):
    return TestClient(build_app(*routers), raise_server_exceptions=False)


def forbidden(response) -> bool:
    """A guard rejection, as opposed to a 404 or a stubbed-data failure."""
    return response.status_code == 403


# ─── clients: read for everyone, write for manager, deactivate for admin ──────

@pytest.mark.parametrize("role", ROLES)
def test_listing_clients_is_open_to_any_authenticated_role(role):
    response = client_as(role).get("/api/v1/commercial/clients")

    assert not forbidden(response)


@pytest.mark.parametrize("role", ["manager", "admin", "superadmin"])
def test_creating_a_client_is_allowed_from_manager_up(role):
    response = client_as(role).post(
        "/api/v1/commercial/clients", json={"nombre": "Acme"}
    )

    assert not forbidden(response)


def test_creating_a_client_is_refused_for_an_employee():
    response = client_as("employee").post(
        "/api/v1/commercial/clients", json={"nombre": "Acme"}
    )

    assert response.status_code == 403


@pytest.mark.parametrize("role", ["employee", "manager"])
def test_deactivating_a_client_is_refused_below_admin(role):
    response = client_as(role).patch(
        f"/api/v1/commercial/clients/{uuid4()}/status", json={"is_active": False}
    )

    assert response.status_code == 403


@pytest.mark.parametrize("role", ["admin", "superadmin"])
def test_deactivating_a_client_is_allowed_from_admin_up(role):
    response = client_as(role).patch(
        f"/api/v1/commercial/clients/{uuid4()}/status", json={"is_active": False}
    )

    assert not forbidden(response)


@pytest.mark.parametrize("role", ["employee", "manager"])
def test_deleting_a_client_is_refused_below_admin(role):
    response = client_as(role).delete(f"/api/v1/commercial/clients/{uuid4()}")

    assert response.status_code == 403


def test_client_deactivation_now_matches_supplier_deactivation():
    """Both were inconsistent before: clients asked manager, suppliers asked admin."""
    manager = client_as("manager", commercial_router, inventory_router)

    clients = manager.patch(
        f"/api/v1/commercial/clients/{uuid4()}/status", json={"is_active": False}
    )
    suppliers = manager.patch(
        f"/api/v1/inventory/suppliers/{uuid4()}/status", json={"is_active": False}
    )

    assert clients.status_code == 403
    assert suppliers.status_code == 403


# ─── sales move stock, so they are a manager operation ────────────────────────

def test_registering_a_sale_is_refused_for_an_employee():
    response = client_as("employee").post(
        "/api/v1/commercial/sales",
        json={"items": [{"producto_id": str(uuid4()), "cantidad": "1.00"}]},
    )

    assert response.status_code == 403


@pytest.mark.parametrize("role", ["manager", "admin", "superadmin"])
def test_registering_a_sale_is_allowed_from_manager_up(role):
    response = client_as(role).post(
        "/api/v1/commercial/sales",
        json={"items": [{"producto_id": str(uuid4()), "cantidad": "1.00"}]},
    )

    assert not forbidden(response)


@pytest.mark.parametrize("role", ROLES)
def test_reading_a_sale_is_open_to_any_authenticated_role(role):
    response = client_as(role).get(f"/api/v1/commercial/sales/{uuid4()}")

    assert not forbidden(response)


# ─── companies: the one endpoint that must exclude admin ──────────────────────

@pytest.mark.parametrize("role", ["employee", "manager", "admin"])
def test_listing_companies_is_refused_for_everyone_below_superadmin(role):
    response = client_as(role, companies_router).get("/api/v1/companies")

    assert response.status_code == 403


def test_listing_companies_is_allowed_for_superadmin():
    response = client_as("superadmin", companies_router).get("/api/v1/companies")

    assert not forbidden(response)


def test_admin_is_excluded_from_companies_despite_the_role_hierarchy():
    """Regression guard: a plain require_role("superadmin") would let admin through."""
    response = client_as("admin", companies_router).get("/api/v1/companies")

    assert response.status_code == 403
    assert response.json()["message"] == "Insufficient permissions"


# ─── users and roles stay admin-only ──────────────────────────────────────────

@pytest.mark.parametrize("role", ["employee", "manager"])
def test_user_administration_is_refused_below_admin(role):
    session = client_as(role, users_router, roles_router)

    assert session.get("/api/v1/users").status_code == 403
    assert session.get("/api/v1/roles").status_code == 403
    assert session.delete(f"/api/v1/users/{uuid4()}").status_code == 403


@pytest.mark.parametrize("role", ["admin", "superadmin"])
def test_user_administration_is_allowed_from_admin_up(role):
    session = client_as(role, users_router, roles_router)

    assert not forbidden(session.get("/api/v1/users"))
    assert not forbidden(session.get("/api/v1/roles"))


# ─── inventory reads stay open, writes stay gated ─────────────────────────────

@pytest.mark.parametrize("role", ROLES)
def test_inventory_reads_are_open_to_any_authenticated_role(role):
    session = client_as(role, inventory_router)

    assert not forbidden(session.get("/api/v1/inventory/products"))
    assert not forbidden(session.get("/api/v1/inventory/suppliers"))
    assert not forbidden(session.get("/api/v1/inventory/movements"))
    assert not forbidden(session.get("/api/v1/inventory/alerts"))
    assert not forbidden(session.get("/api/v1/inventory/supplier-products"))


def test_inventory_writes_are_refused_for_an_employee():
    session = client_as("employee", inventory_router)

    assert session.post(
        "/api/v1/inventory/products", json={"sku": "A1", "nombre": "Producto"}
    ).status_code == 403
    assert session.post(
        "/api/v1/inventory/suppliers", json={"nombre": "Acme"}
    ).status_code == 403


@pytest.mark.parametrize("role", ["employee", "manager"])
def test_product_and_supplier_deactivation_is_refused_below_admin(role):
    session = client_as(role, inventory_router)

    assert session.patch(
        f"/api/v1/inventory/products/{uuid4()}/status", json={"is_active": False}
    ).status_code == 403
    assert session.delete(
        f"/api/v1/inventory/suppliers/{uuid4()}"
    ).status_code == 403


# ─── company registration is a superadmin action ──────────────────────────────

REGISTRATION = {
    "name": "Empresa Nueva",
    "admin_username": "nuevo_admin",
    "admin_email": "nuevo.admin@test.com",
}


@pytest.mark.parametrize("role", ["employee", "manager", "admin"])
def test_registering_a_company_is_refused_below_superadmin(role):
    response = client_as(role, auth_router).post(
        "/api/v1/auth/register", json=REGISTRATION
    )

    assert response.status_code == 403


def test_registering_a_company_is_allowed_for_superadmin():
    response = client_as("superadmin", auth_router).post(
        "/api/v1/auth/register", json=REGISTRATION
    )

    assert not forbidden(response)


def test_registering_a_company_requires_authentication():
    """It used to be wide open, despite the docstring saying superadmin only."""
    response = anonymous_client(auth_router).post(
        "/api/v1/auth/register", json=REGISTRATION
    )

    assert response.status_code == 401


def test_login_and_password_recovery_stay_public():
    """Login also answers 401, so compare the reason rather than the status."""
    session = anonymous_client(auth_router)

    login = session.post(
        "/api/v1/auth/login", json={"email": "a@test.com", "password": "x"}
    )
    assert login.json()["message"] == "Invalid credentials"

    assert session.post(
        "/api/v1/auth/password/forgot", json={"email": "a@test.com"}
    ).status_code != 401


def test_no_security_scheme_is_attached_to_the_public_auth_routes():
    schema = build_app(auth_router).openapi()

    public = ["/api/v1/auth/login", "/api/v1/auth/password/forgot", "/api/v1/auth/password/reset"]
    for path in public:
        assert "security" not in schema["paths"][path]["post"], path

    assert "security" in schema["paths"]["/api/v1/auth/register"]["post"]
