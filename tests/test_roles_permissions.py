import pytest
from types import SimpleNamespace
from app.api.dependencies.auth import require_role
from app.utils.exceptions import AppError

def test_superadmin_passes_admin_check():
    checker = require_role("admin")
    user = SimpleNamespace(role=SimpleNamespace(name="superadmin"))

    assert checker(user) is user

def test_admin_passes_admin_check():
    checker = require_role("admin")
    user = SimpleNamespace(role=SimpleNamespace(name="admin"))

    assert checker(user) is user

def test_employee_fails_admin_check():
    checker = require_role("admin")
    user = SimpleNamespace(role=SimpleNamespace(name="employee"))

    with pytest.raises(AppError):
        checker(user)

def test_manager_fails_admin_check():
    checker = require_role("admin")
    user = SimpleNamespace(role=SimpleNamespace(name="manager"))

    with pytest.raises(AppError):
        checker(user)

def test_require_role_without_roles():
    checker = require_role()
    user = SimpleNamespace(role=SimpleNamespace(name="employee"))

    assert checker(user) is user