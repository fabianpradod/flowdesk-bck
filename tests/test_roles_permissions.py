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

def test_strict_superadmin_check_rejects_admin():
    checker = require_role("superadmin", strict=True)
    user = SimpleNamespace(role=SimpleNamespace(name="admin"))

    with pytest.raises(AppError):
        checker(user)

def test_strict_superadmin_check_passes_superadmin():
    checker = require_role("superadmin", strict=True)
    user = SimpleNamespace(role=SimpleNamespace(name="superadmin"))

    assert checker(user) is user

def test_strict_check_ignores_the_role_hierarchy():
    checker = require_role("manager", strict=True)

    manager = SimpleNamespace(role=SimpleNamespace(name="manager"))
    assert checker(manager) is manager

    for name in ("admin", "superadmin", "employee"):
        with pytest.raises(AppError):
            checker(SimpleNamespace(role=SimpleNamespace(name=name)))

def test_non_strict_superadmin_check_still_admits_admin():
    """The hierarchy is why strict mode had to exist; keep it pinned."""
    checker = require_role("superadmin")
    user = SimpleNamespace(role=SimpleNamespace(name="admin"))

    assert checker(user) is user

def test_strict_check_without_roles_is_rejected_at_definition():
    with pytest.raises(ValueError):
        require_role(strict=True)

def test_user_without_a_role_is_refused():
    checker = require_role("employee")
    user = SimpleNamespace(role=None)

    with pytest.raises(AppError):
        checker(user)
