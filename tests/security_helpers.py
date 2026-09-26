"""Shared pieces for the security test files.

ROUTE_POLICY is the single table of who may call each route. The inventory test
checks it against the routes the app really registers, so a new endpoint cannot
ship without being classified here first.
"""

import re
from types import SimpleNamespace
from uuid import uuid4

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.api.dependencies.auth import get_current_user, get_db

PUBLIC = "public"
AUTHENTICATED = "authenticated"
OWNER = "owner"
MANAGER = "manager"
ADMIN = "admin"
SUPERADMIN_STRICT = "superadmin_strict"

ROLES = ("employee", "manager", "admin", "superadmin")

# Roles that pass each policy. OWNER admits every role at the route level; the
# service then limits each user to their own records.
ALLOWED_ROLES = {
    PUBLIC: set(ROLES),
    AUTHENTICATED: set(ROLES),
    OWNER: set(ROLES),
    MANAGER: {"manager", "admin", "superadmin"},
    ADMIN: {"admin", "superadmin"},
    SUPERADMIN_STRICT: {"superadmin"},
}

ROUTE_POLICY = {
    # system
    ("GET", "/"): PUBLIC,
    ("GET", "/health"): PUBLIC,
    ("GET", "/ready"): PUBLIC,
    # auth
    ("POST", "/api/v1/auth/login"): PUBLIC,
    ("POST", "/api/v1/auth/password/set"): PUBLIC,
    ("POST", "/api/v1/auth/password/forgot"): PUBLIC,
    ("POST", "/api/v1/auth/password/reset"): PUBLIC,
    ("POST", "/api/v1/auth/register"): SUPERADMIN_STRICT,
    ("GET", "/api/v1/auth/employees"): ADMIN,
    ("POST", "/api/v1/auth/employees"): ADMIN,
    ("POST", "/api/v1/auth/invitations/resend"): ADMIN,
    # companies, users and roles
    ("GET", "/api/v1/companies"): SUPERADMIN_STRICT,
    ("GET", "/api/v1/users"): ADMIN,
    ("PUT", "/api/v1/users/{user_id}"): ADMIN,
    ("PATCH", "/api/v1/users/{user_id}/status"): ADMIN,
    ("DELETE", "/api/v1/users/{user_id}"): ADMIN,
    ("GET", "/api/v1/roles"): ADMIN,
    # inventory
    ("GET", "/api/v1/inventory/suppliers"): AUTHENTICATED,
    ("POST", "/api/v1/inventory/suppliers"): MANAGER,
    ("GET", "/api/v1/inventory/suppliers/{supplier_id}"): AUTHENTICATED,
    ("PUT", "/api/v1/inventory/suppliers/{supplier_id}"): MANAGER,
    ("PATCH", "/api/v1/inventory/suppliers/{supplier_id}/status"): ADMIN,
    ("DELETE", "/api/v1/inventory/suppliers/{supplier_id}"): ADMIN,
    ("GET", "/api/v1/inventory/products"): AUTHENTICATED,
    ("POST", "/api/v1/inventory/products"): MANAGER,
    ("PATCH", "/api/v1/inventory/products/{product_id}/status"): ADMIN,
    ("POST", "/api/v1/inventory/products/import"): MANAGER,
    ("GET", "/api/v1/inventory/movements"): AUTHENTICATED,
    ("POST", "/api/v1/inventory/movements"): MANAGER,
    ("GET", "/api/v1/inventory/alerts"): AUTHENTICATED,
    ("GET", "/api/v1/inventory/analytics/monthly"): MANAGER,
    ("GET", "/api/v1/inventory/analytics/trend"): MANAGER,
    ("GET", "/api/v1/inventory/analytics/products"): MANAGER,
    ("GET", "/api/v1/inventory/metrics"): MANAGER,
    ("GET", "/api/v1/inventory/history"): MANAGER,
    ("GET", "/api/v1/inventory/supplier-products"): AUTHENTICATED,
    # commercial
    ("GET", "/api/v1/commercial/clients"): AUTHENTICATED,
    ("POST", "/api/v1/commercial/clients"): MANAGER,
    ("GET", "/api/v1/commercial/clients/{client_id}"): AUTHENTICATED,
    ("PUT", "/api/v1/commercial/clients/{client_id}"): MANAGER,
    ("PATCH", "/api/v1/commercial/clients/{client_id}/status"): ADMIN,
    ("DELETE", "/api/v1/commercial/clients/{client_id}"): ADMIN,
    ("GET", "/api/v1/commercial/clients/{client_id}/purchases"): AUTHENTICATED,
    ("POST", "/api/v1/commercial/sales"): MANAGER,
    ("GET", "/api/v1/commercial/sales/{sale_id}"): AUTHENTICATED,
    # reports
    ("GET", "/api/v1/reports/history"): ADMIN,
    ("GET", "/api/v1/reports/inventario"): ADMIN,
    ("GET", "/api/v1/reports/movimientos"): ADMIN,
    ("GET", "/api/v1/reports/alertas"): ADMIN,
    # tasks
    ("GET", "/api/v1/tasks"): OWNER,
    ("POST", "/api/v1/tasks"): OWNER,
    ("GET", "/api/v1/tasks/{task_id}"): OWNER,
    ("PUT", "/api/v1/tasks/{task_id}"): OWNER,
    ("PATCH", "/api/v1/tasks/{task_id}/status"): OWNER,
    ("DELETE", "/api/v1/tasks/{task_id}"): OWNER,
}

# What the guard on the route must look like for each policy.
EXPECTED_GUARD = {
    PUBLIC: None,
    AUTHENTICATED: ("require_role", (), False),
    OWNER: ("get_current_user",),
    MANAGER: ("require_role", ("manager",), False),
    ADMIN: ("require_role", ("admin",), False),
    SUPERADMIN_STRICT: ("require_role", ("superadmin",), True),
}


def api_routes(app):
    """Every (method, path, route) the app registers, docs pages excluded."""
    return [
        (method, route.path, route)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in sorted(route.methods)
    ]


def protected_routes(policy=ROUTE_POLICY):
    return sorted(key for key, value in policy.items() if value != PUBLIC)


def route_guard(route: APIRoute):
    """Describe the auth dependency declared directly on a route.

    require_role returns a closure, so its arguments are read from the closure
    cells. Nested dependencies are ignored on purpose: the checker itself depends
    on get_current_user, and only the outermost guard says what the route allows.
    """
    for dependency in route.dependant.dependencies:
        call = dependency.call
        if getattr(call, "__qualname__", "") == "require_role.<locals>.checker":
            cells = dict(zip(call.__code__.co_freevars, call.__closure__ or ()))
            return ("require_role", cells["roles"].cell_contents, cells["strict"].cell_contents)
        if call is get_current_user:
            return ("get_current_user",)
    return None


def fill_path(path: str, value) -> str:
    """Replace every {param} in a route path with the same value."""
    parts = []
    for part in path.split("/"):
        parts.append(str(value) if part.startswith("{") and part.endswith("}") else part)
    return "/".join(parts)


# Refusal message raised by require_role. Other 403s (inactive company, user with
# no tenant) come from elsewhere and are not a role decision.
GUARD_REFUSAL = "Insufficient permissions"


class FakeResult:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def one(self):
        return self.rows[0]

    def one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        return None

    def scalar_one(self):
        return 0

    def all(self):
        return self.rows

    def __iter__(self):
        return iter(self.rows)


class FakeQuery:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def filter(self, *_args, **_kwargs):
        return self

    def join(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class RecordingDB:
    """Answers every read with no rows and records what was asked.

    `statements` holds each Core statement passed to execute and `queried` each
    ORM model passed to query, so a test can prove a request never reached the
    data, or which tenant schema it reached.
    """

    def __init__(self, query_rows=None):
        self.statements = []
        self.queried = []
        self.commits = 0
        # ORM rows to hand back per model, e.g. {User: [user]} so the real
        # get_current_user can find the token's owner.
        self.query_rows = query_rows or {}

    def execute(self, statement, *_args, **_kwargs):
        self.statements.append(statement)
        return FakeResult()

    def query(self, model):
        self.queried.append(model)
        return FakeQuery(self.query_rows.get(model, ()))

    def add(self, _obj):
        pass

    def flush(self):
        pass

    def refresh(self, _obj):
        pass

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def connection(self):
        return None

    @property
    def touched(self) -> bool:
        return bool(self.statements or self.queried)


def make_company(*, is_active=True, name="Acme"):
    company_id = uuid4()
    return SimpleNamespace(
        id=company_id,
        name=name,
        schema_name=f"tenant_{company_id.hex}",
        is_active=is_active,
    )


def make_user(role_name, company=None, *, is_active=True):
    """A user as get_current_user would return it.

    A superadmin gets no company unless one is passed, like the seeded one.
    """
    if company is None and role_name != "superadmin":
        company = make_company()
    return SimpleNamespace(
        id=uuid4(),
        username=f"{role_name}_{uuid4().hex[:6]}",
        email=f"{role_name}.{uuid4().hex[:6]}@test.com",
        company_id=company.id if company else None,
        company=company,
        is_active=is_active,
        role=SimpleNamespace(name=role_name) if role_name else None,
    )


def client_for(user, db=None):
    """TestClient on the real app, signed in as `user`, over a RecordingDB."""
    from main import app

    db = db if db is not None else RecordingDB()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


def token_client(db):
    """TestClient on the real app over `db`, keeping the real get_current_user so
    the Authorization header is what decides who is calling."""
    from main import app

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides.pop(get_current_user, None)
    return TestClient(app, raise_server_exceptions=False)


def call(session, key, value=None, **kwargs):
    method, path = key
    return session.request(method, fill_path(path, value or uuid4()), **kwargs)


def refused_by_guard(response) -> bool:
    return response.status_code == 403 and response.json().get("message") == GUARD_REFUSAL


TENANT_PREFIXES = (
    "/api/v1/inventory",
    "/api/v1/commercial",
    "/api/v1/reports",
    "/api/v1/tasks",
)

_SCHEMA_RE = re.compile(r"tenant_[0-9a-f]{32}")


def tenant_routes(policy=ROUTE_POLICY):
    return [key for key in protected_routes(policy) if key[1].startswith(TENANT_PREFIXES)]


def schemas_in(statements) -> set[str]:
    """Tenant schemas named by a list of executed Core statements."""
    found = set()
    for statement in statements:
        sql = str(statement.compile(dialect=postgresql.dialect()))
        found.update(_SCHEMA_RE.findall(sql))
    return found


def request_kwargs(key, ref=None) -> dict:
    """A request body that passes validation for `key`, so the call reaches the
    service. `ref` is used for every id the body points at, which lets the
    cross-tenant tests aim all of them at another company's records at once."""
    ref = str(ref or uuid4())
    method, path = key
    bodies = {
        ("POST", "/api/v1/inventory/suppliers"): {"nombre": "Acme"},
        ("PUT", "/api/v1/inventory/suppliers/{supplier_id}"): {"nombre": "Acme 2"},
        ("PATCH", "/api/v1/inventory/suppliers/{supplier_id}/status"): {"is_active": False},
        ("POST", "/api/v1/inventory/products"): {"sku": "sku-1", "nombre": "Prod", "proveedor_id": ref},
        ("PATCH", "/api/v1/inventory/products/{product_id}/status"): {"is_active": False},
        ("POST", "/api/v1/inventory/movements"): {
            "producto_id": ref, "tipo_movimiento": "entrada_manual", "cantidad": "1",
        },
        ("POST", "/api/v1/commercial/clients"): {"nombre": "Cliente"},
        ("PUT", "/api/v1/commercial/clients/{client_id}"): {"nombre": "Cliente 2"},
        ("PATCH", "/api/v1/commercial/clients/{client_id}/status"): {"is_active": False},
        ("POST", "/api/v1/commercial/sales"): {
            "cliente_id": ref, "items": [{"producto_id": ref, "cantidad": "1"}],
        },
        ("POST", "/api/v1/tasks"): {"titulo": "Tarea"},
        ("PUT", "/api/v1/tasks/{task_id}"): {"titulo": "Tarea 2"},
        ("PATCH", "/api/v1/tasks/{task_id}/status"): {"estado": "completada"},
        ("POST", "/api/v1/auth/register"): {
            "name": "Otra", "admin_email": "otra@test.com", "admin_username": "otra_admin",
        },
        ("POST", "/api/v1/auth/employees"): {"username": "nuevo", "email": "nuevo@test.com", "role_id": 4},
        ("POST", "/api/v1/auth/invitations/resend"): {"email": "nadie@test.com"},
        ("PUT", "/api/v1/users/{user_id}"): {"username": "renombrado"},
        ("PATCH", "/api/v1/users/{user_id}/status"): {"is_active": False},
    }
    if key == ("POST", "/api/v1/inventory/products/import"):
        return {"files": {"file": ("productos.csv", b"sku,nombre\nsku-1,Prod\n", "text/csv")}}
    if key in bodies:
        return {"json": bodies[key]}
    return {}
