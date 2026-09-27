"""Protected endpoints must refuse requests without valid credentials.

Every non public route in ROUTE_POLICY is called through the real app, with the
real get_current_user, once per broken credential. The only acceptable answers
are 401 or 403 in the JSON error contract: never data, never a 500.
"""

import base64
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from app.core.config import ALGORITHM, DEMO_USER_PASSWORD, SECRET_KEY
from app.core.security import create_access_token
from app.models.users import User
from main import app
from tests.security_helpers import fill_path, protected_routes

PROTECTED = protected_routes()


def _seeded(email):
    return next(user for user in app.state.test_db.data[User] if user.email == email)


def _access_token(user):
    return create_access_token({"sub": str(user.id), "role": user.role.name})


def _unsigned(claims):
    def encode(part):
        return base64.urlsafe_b64encode(json.dumps(part).encode()).rstrip(b"=").decode()

    return f"{encode({'alg': 'none', 'typ': 'JWT'})}.{encode(claims)}."


def _admin():
    return _seeded("admin.demo@flowdesk.com")


# Each case returns the Authorization header to send, or None for no header.
CREDENTIALS = {
    "no header": lambda: None,
    "empty bearer": lambda: "Bearer ",
    "basic scheme": lambda: "Basic YWRtaW46YWRtaW4=",
    "malformed token": lambda: "Bearer not.a.jwt",
    "wrong signature": lambda: "Bearer " + jwt.encode(
        {"sub": str(_admin().id), "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
        "not-the-server-key",
        algorithm=ALGORITHM,
    ),
    "expired token": lambda: "Bearer " + create_access_token(
        {"sub": str(_admin().id)}, expires_delta=timedelta(minutes=-1)
    ),
    "alg none": lambda: "Bearer " + _unsigned(
        {"sub": str(_admin().id), "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp())}
    ),
    "set password token": lambda: "Bearer " + create_access_token(
        {"sub": str(_admin().id), "purpose": "set_password"}, expires_delta=timedelta(hours=48)
    ),
    "reset password token": lambda: "Bearer " + create_access_token(
        {"sub": str(_admin().id), "purpose": "reset_password"}, expires_delta=timedelta(hours=48)
    ),
    "token without sub": lambda: "Bearer " + create_access_token({"role": "admin"}),
    "sub is not a uuid": lambda: "Bearer " + create_access_token({"sub": "admin"}),
    "user does not exist": lambda: "Bearer " + create_access_token({"sub": str(uuid4())}),
}


@pytest.fixture
def anonymous():
    return TestClient(app, raise_server_exceptions=False)


def _call(session, method, path, header):
    headers = {"Authorization": header} if header is not None else {}
    return session.request(method, fill_path(path, uuid4()), headers=headers)


@pytest.mark.parametrize("case", sorted(CREDENTIALS))
@pytest.mark.parametrize("key", PROTECTED, ids=lambda key: f"{key[0]} {key[1]}")
def test_protected_route_refuses_invalid_credentials(anonymous, key, case):
    method, path = key

    response = _call(anonymous, method, path, CREDENTIALS[case]())

    assert response.status_code == 401, response.text
    body = response.json()
    assert set(body) == {"message", "code", "errors"}


@pytest.mark.parametrize("key", PROTECTED, ids=lambda key: f"{key[0]} {key[1]}")
def test_protected_route_refuses_an_inactive_user(anonymous, key):
    method, path = key
    inactive = _seeded("inactive@test.com")

    response = _call(anonymous, method, path, "Bearer " + _access_token(inactive))

    assert response.status_code == 403, response.text
    assert response.json()["message"] == "Account is inactive"


def test_the_token_signature_is_what_is_trusted_not_the_claims():
    """Sanity check for the cases above: a real token for the same user works."""
    session = TestClient(app, raise_server_exceptions=False)

    response = session.get(
        "/api/v1/users", headers={"Authorization": "Bearer " + _access_token(_admin())}
    )

    assert response.status_code == 200


def test_a_token_from_login_opens_a_session():
    session = TestClient(app, raise_server_exceptions=False)

    login = session.post(
        "/api/v1/auth/login",
        json={"email": "admin.demo@flowdesk.com", "password": DEMO_USER_PASSWORD},
    )
    token = login.json()["access_token"]

    response = session.get("/api/v1/roles", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200


def test_password_tokens_still_work_on_their_own_endpoints():
    """Refusing them as sessions must not break the invitation flow they exist for."""
    session = TestClient(app, raise_server_exceptions=False)
    user = _seeded("inactive@test.com")
    user.password = ""
    token = create_access_token(
        {"sub": str(user.id), "purpose": "set_password"}, expires_delta=timedelta(hours=48)
    )

    response = session.post(
        "/api/v1/auth/password/set", json={"token": token, "new_password": "Another123!"}
    )

    assert response.status_code == 200
    assert user.is_active is True


def test_the_server_key_is_configured():
    """Every case above leans on it. A missing key would make them meaningless."""
    assert SECRET_KEY


class _DatabaseThatMustNotBeQueried:
    """Postgres answers a non UUID id with a cast error, which surfaced as a 500."""

    def query(self, _model):
        raise AssertionError("the token subject reached the database")


@pytest.mark.parametrize("claims", [{"role": "admin"}, {"sub": "admin"}, {"sub": ""}, {"sub": None}])
def test_a_bad_subject_is_refused_before_touching_the_database(claims):
    from app.api.dependencies.auth import get_current_user
    from app.utils.exceptions import AppError

    with pytest.raises(AppError) as refused:
        get_current_user(create_access_token(claims), _DatabaseThatMustNotBeQueried())

    assert refused.value.status_code == 401


@pytest.mark.parametrize("path, purpose", [
    ("/api/v1/auth/password/set", "set_password"),
    ("/api/v1/auth/password/reset", "reset_password"),
])
@pytest.mark.parametrize("claims", [{}, {"sub": "admin"}])
def test_password_endpoints_refuse_a_token_without_a_valid_subject(anonymous, path, purpose, claims):
    token = create_access_token({**claims, "purpose": purpose})

    response = anonymous.post(path, json={"token": token, "new_password": "Another123!"})

    assert response.status_code == 400
    assert response.json()["message"] == "Invalid or expired token"
