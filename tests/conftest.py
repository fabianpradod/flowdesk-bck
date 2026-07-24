import pytest
from fastapi.testclient import TestClient
from main import app
from app.api.dependencies.auth import get_current_user
from tests.auth_helpers import admin_user
from tests.auth_helpers import superadmin_user
from tests.auth_helpers import employee_user
import app.services.auth as auth_service

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture(autouse = True)
def clear_rate_limit():
    auth_service._reset_attempts.clear()

    yield

    auth_service._reset_attempts.clear()

@pytest.fixture
def admin_client():
    app.dependency_overrides[get_current_user] = lambda: admin_user()

    yield TestClient(app)

    app.dependency_overrides.clear()

@pytest.fixture
def superadmin_client():
    app.dependency_overrides[get_current_user] = lambda: superadmin_user()

    yield TestClient(app)

    app.dependency_overrides.clear()

@pytest.fixture
def employee_client():
    app.dependency_overrides[get_current_user] = lambda: employee_user()

    yield TestClient(app)

    app.dependency_overrides.clear()