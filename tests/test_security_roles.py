"""Every role reaches what the permission matrix allows it to.

Each protected route in ROUTE_POLICY is called once per role through the real app.
The database answers with no rows, so a 404 or a 422 is a fine outcome here: what
matters is that the role guard let the request through.
"""

import pytest

from tests.security_helpers import (
    ALLOWED_ROLES,
    ROLES,
    ROUTE_POLICY,
    call,
    client_for,
    make_user,
    protected_routes,
    refused_by_guard,
)


def _cases(allowed: bool):
    return [
        (key, role)
        for key in protected_routes()
        for role in ROLES
        if (role in ALLOWED_ROLES[ROUTE_POLICY[key]]) is allowed
    ]


def _case_id(case):
    (method, path), role = case
    return f"{role} {method} {path}"


ALLOWED = _cases(allowed=True)


@pytest.mark.parametrize("case", ALLOWED, ids=[_case_id(case) for case in ALLOWED])
def test_allowed_role_passes_the_guard(case):
    key, role = case

    response = call(client_for(make_user(role)), key)

    assert response.status_code != 401, response.text
    assert not refused_by_guard(response), response.text


def test_the_matrix_admits_every_role_somewhere_and_superadmin_everywhere():
    """Guards against a policy table that silently locks a role out."""
    reachable = {role for _key, role in ALLOWED}

    assert reachable == set(ROLES)
    assert all(
        "superadmin" in ALLOWED_ROLES[ROUTE_POLICY[key]] for key in protected_routes()
    )


@pytest.mark.parametrize("role", ["manager", "admin"])
def test_a_superadmin_only_route_is_not_reachable_through_the_hierarchy(role):
    """The one place where the hierarchy is switched off on purpose."""
    strict = [key for key, policy in ROUTE_POLICY.items() if policy == "superadmin_strict"]

    assert strict
    for key in strict:
        assert refused_by_guard(call(client_for(make_user(role)), key)), key
