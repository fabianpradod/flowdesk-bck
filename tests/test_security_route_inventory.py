"""Inventory of the routes that need authentication and authorization.

The app is the source of truth for which routes exist, ROUTE_POLICY for who may
call them. These tests keep both in step: a route added without a policy, a
policy left behind by a removed route, or a guard that drifts from its policy all
fail here.
"""

import pytest

from main import app
from tests.security_helpers import (
    EXPECTED_GUARD,
    PUBLIC,
    ROUTE_POLICY,
    api_routes,
    route_guard,
)

REGISTERED = {(method, path): route for method, path, route in api_routes(app)}


def test_every_registered_route_has_a_policy():
    missing = sorted(set(REGISTERED) - set(ROUTE_POLICY))

    assert not missing, f"Classify these routes in ROUTE_POLICY: {missing}"


def test_every_policy_matches_a_registered_route():
    stale = sorted(set(ROUTE_POLICY) - set(REGISTERED))

    assert not stale, f"These routes no longer exist: {stale}"


@pytest.mark.parametrize("key", sorted(ROUTE_POLICY), ids=lambda key: f"{key[0]} {key[1]}")
def test_route_guard_matches_its_policy(key):
    route = REGISTERED[key]

    assert route_guard(route) == EXPECTED_GUARD[ROUTE_POLICY[key]]


def test_only_the_expected_routes_are_public():
    public = sorted(key for key, policy in ROUTE_POLICY.items() if policy == PUBLIC)

    assert public == [
        ("GET", "/"),
        ("GET", "/health"),
        ("GET", "/ready"),
        ("POST", "/api/v1/auth/login"),
        ("POST", "/api/v1/auth/password/forgot"),
        ("POST", "/api/v1/auth/password/reset"),
        ("POST", "/api/v1/auth/password/set"),
    ]


@pytest.mark.parametrize("key", sorted(ROUTE_POLICY), ids=lambda key: f"{key[0]} {key[1]}")
def test_openapi_security_scheme_matches_the_policy(key):
    """The frontend and /docs read this to decide whether to send the token."""
    method, path = key
    operation = app.openapi()["paths"][path][method.lower()]

    if ROUTE_POLICY[key] == PUBLIC:
        assert "security" not in operation
    else:
        assert operation["security"] == [{"OAuth2PasswordBearer": []}]
