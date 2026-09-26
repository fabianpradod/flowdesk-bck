"""Shared pieces for the security test files.

ROUTE_POLICY is the single table of who may call each route. The inventory test
checks it against the routes the app really registers, so a new endpoint cannot
ship without being classified here first.
"""

from fastapi.routing import APIRoute

from app.api.dependencies.auth import get_current_user

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
