"""A user cannot read or write data that belongs to another company.

Tenant data lives in one schema per company, so isolation holds as long as every
statement a request runs names the caller's schema and no other. These tests
record the statements and check exactly that, for every tenant route. The global
tables (users, companies) are shared, so their filters are checked separately.
"""

from datetime import timedelta

import pytest

from app.core.config import DEMO_USER_PASSWORD
from app.core.security import create_access_token
from app.models.companies import Company
from app.models.users import User
from main import app
from tests.security_helpers import (
    ALLOWED_ROLES,
    ROUTE_POLICY,
    RecordingDB,
    add_company_with_users,
    call,
    client_for,
    make_company,
    make_user,
    protected_routes,
    request_kwargs,
    schemas_in,
    tenant_routes,
    token_client,
)

TENANT_ROUTES = tenant_routes()


def _lowest_allowed_role(key):
    for role in ("employee", "manager", "admin", "superadmin"):
        if role in ALLOWED_ROLES[ROUTE_POLICY[key]]:
            return role


def _route_id(key):
    return f"{key[0]} {key[1]}"


# Tenant schemas

@pytest.mark.parametrize("key", TENANT_ROUTES, ids=_route_id)
def test_tenant_route_only_touches_the_callers_schema(key):
    company_a, company_b = make_company(name="A"), make_company(name="B")
    db = RecordingDB()
    user = make_user(_lowest_allowed_role(key), company_a)

    call(client_for(user, db), key, **request_kwargs(key))

    assert db.statements, "the request never reached the tenant tables"
    assert schemas_in(db.statements) == {company_a.schema_name}
    assert company_b.schema_name not in schemas_in(db.statements)


@pytest.mark.parametrize("key", TENANT_ROUTES, ids=_route_id)
def test_the_schema_claims_in_the_token_are_ignored(key):
    """The token says company B; the database says company A. The database wins."""
    company_a, company_b = make_company(name="A"), make_company(name="B")
    user = make_user("admin", company_a)
    db = RecordingDB(query_rows={User: [user]})
    token = create_access_token({
        "sub": str(user.id),
        "role": "superadmin",
        "company_id": str(company_b.id),
        "schema_name": company_b.schema_name,
    })
    session = token_client(db)

    call(session, key, headers={"Authorization": f"Bearer {token}"}, **request_kwargs(key))

    assert schemas_in(db.statements) == {company_a.schema_name}


@pytest.mark.parametrize("key", TENANT_ROUTES, ids=_route_id)
def test_a_user_without_a_company_never_reaches_tenant_data(key):
    """An otherwise allowed role still needs a company, independently of its guard."""
    db = RecordingDB()
    user = make_user(_lowest_allowed_role(key))
    user.company_id = None
    user.company = None

    response = call(client_for(user, db), key, **request_kwargs(key))

    assert response.status_code == 403
    assert response.json()["message"] == "This user is not assigned to a tenant company"
    assert not db.statements


# Inactive companies

@pytest.mark.parametrize("key", protected_routes(), ids=_route_id)
def test_a_user_of_an_inactive_company_is_refused_everywhere(key):
    """Tenant routes already refused them; users, employees and roles did not."""
    company = make_company(is_active=False)
    user = make_user("admin", company)
    db = RecordingDB(query_rows={User: [user]})
    token = create_access_token({"sub": str(user.id)})
    session = token_client(db)

    response = call(session, key, headers={"Authorization": f"Bearer {token}"}, **request_kwargs(key))

    assert response.status_code == 403, response.text
    assert response.json()["message"] == "Company is inactive"
    assert not db.statements


def test_a_user_of_an_inactive_company_cannot_log_in(client):
    company = app.state.test_db.data[Company][0]
    company.is_active = False

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin.demo@flowdesk.com", "password": DEMO_USER_PASSWORD},
    )

    assert response.status_code == 403
    assert response.json()["message"] == "Company is inactive"
    assert "access_token" not in response.json()


def test_wrong_credentials_still_answer_401_for_an_inactive_company(client):
    """The company check must not tell a guesser which emails exist."""
    app.state.test_db.data[Company][0].is_active = False

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin.demo@flowdesk.com", "password": "wrong-password"},
    )

    assert response.status_code == 401


# Global tables

@pytest.fixture
def second_company():
    return add_company_with_users(app.state.test_db)


@pytest.mark.parametrize("path", ["/api/v1/users", "/api/v1/auth/employees"])
def test_admin_listings_only_show_the_admins_company(admin_client, second_company, path):
    company_b, _users = second_company

    response = admin_client.get(path)

    assert response.status_code == 200
    company_ids = {row["company_id"] for row in response.json()}
    assert str(company_b.id) not in company_ids
    assert len(company_ids) == 1


@pytest.mark.parametrize("path", ["/api/v1/users", "/api/v1/auth/employees"])
def test_superadmin_listings_span_every_company(superadmin_client, second_company, path):
    """Cross-company reads are what the superadmin role is for."""
    company_b, _users = second_company

    response = superadmin_client.get(path)

    assert str(company_b.id) in {row["company_id"] for row in response.json()}


def test_the_token_owner_is_resolved_from_the_database_not_the_claims():
    """A token naming another role or company changes nothing: role and company
    are read from the user row on every request."""
    company = make_company()
    user = make_user("employee", company)
    db = RecordingDB(query_rows={User: [user]})
    token = create_access_token({"sub": str(user.id), "role": "admin"}, expires_delta=timedelta(minutes=5))
    response = token_client(db).get(
        "/api/v1/users", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 403
    assert response.json()["message"] == "Insufficient permissions"
