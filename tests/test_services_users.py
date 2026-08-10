from uuid import uuid4
import pytest
from app.models.roles import Role
from app.models.users import User
from app.schemas.users import UserStatusUpdate, UserUpdate
from app.services import users as users_service
from app.utils.exceptions import AppError

def _user(db, identifier):
    for user in db.data[User]:
        if (user.email == identifier or getattr(user, "username", None) == identifier):
            return user

    raise AssertionError(f"User {identifier} not found")

def _role(db, name):
    for role in db.data[Role]:
        if role.name == name:
            return role
    raise AssertionError(f"Role {name} not found")

def test_get_users_superadmin_returns_all(seed_test_db):
    db = seed_test_db

    superadmin = _user(db, "superadmin@test.com")

    result = users_service.get_users(db, superadmin)

    assert len(result) == 5
    assert {user.username for user in result} == {
        "superadmin",
        "demo_admin",
        "demo_manager",
        "demo_employee",
        "inactive_user",
    }

def test_get_users_regular_user_returns_company_users(seed_test_db):
    db = seed_test_db

    admin = _user(db, "admin.demo@flowdesk.com")

    result = users_service.get_users(db, admin)

    assert len(result) == 4
    assert all(user.company_id == admin.company_id for user in result)

def test_update_user_username(seed_test_db):
    db = seed_test_db

    admin = _user(db, "admin.demo@flowdesk.com")
    target = _user(db, "demo_employee")

    data = UserUpdate(username="employee_updated")

    result = users_service.update_user(
        db,
        target.id,
        data,
        admin,
    )

    assert result.username == "employee_updated"
    assert db.commits == 1
    assert result in db.refreshed

def test_update_user_role(seed_test_db):
    db = seed_test_db

    admin = _user(db, "admin.demo@flowdesk.com")
    target = _user(db, "demo_employee")
    manager_role = _role(db, "manager")

    data = UserUpdate(role_id=manager_role.id)

    result = users_service.update_user(
        db,
        target.id,
        data,
        admin,
    )

    assert result.role_id == manager_role.id
    assert db.commits == 1

def test_update_user_username_and_role(seed_test_db):
    db = seed_test_db

    admin = _user(db, "admin.demo@flowdesk.com")
    target = _user(db, "demo_employee")
    manager_role = _role(db, "manager")

    data = UserUpdate(
        username="new_employee",
        role_id=manager_role.id,
    )

    result = users_service.update_user(
        db,
        target.id,
        data,
        admin,
    )

    assert result.username == "new_employee"
    assert result.role_id == manager_role.id

def test_update_user_not_found(seed_test_db):
    db = seed_test_db
    admin = _user(db, "admin.demo@flowdesk.com")

    with pytest.raises(AppError) as exc:
        users_service.update_user(
            db,
            uuid4(),
            UserUpdate(username="test"),
            admin,
        )

    assert exc.value.status_code == 404
    assert "User not found" in exc.value.message

def test_update_user_cross_company_forbidden(seed_test_db):
    db = seed_test_db
    admin = _user(db, "admin.demo@flowdesk.com")

    other_company_user = User(
        username="other_company",
        email="other@test.com",
        password="password",
        role_id=_role(db, "employee").id,
        company_id=uuid4(),
        is_active=True,
    )
    other_company_user.id = uuid4()
    other_company_user.role = _role(db, "employee")

    db.data[User].append(other_company_user)

    with pytest.raises(AppError) as exc:
        users_service.update_user(
            db,
            other_company_user.id,
            UserUpdate(username="hacked"),
            admin,
        )

    assert exc.value.status_code == 403

def test_update_superadmin_user_forbidden(seed_test_db):
    db = seed_test_db

    admin = _user(db, "admin.demo@flowdesk.com")
    superadmin = _user(db, "superadmin@test.com")

    with pytest.raises(AppError) as exc:
        users_service.update_user(
            db,
            superadmin.id,
            UserUpdate(username="changed"),
            admin,
        )

    assert exc.value.status_code == 403
    assert "superadmin" in exc.value.message.lower()

def test_update_user_role_not_found(seed_test_db):
    db = seed_test_db

    admin = _user(db, "admin.demo@flowdesk.com")
    target = _user(db, "demo_employee")

    with pytest.raises(AppError) as exc:
        users_service.update_user(
            db,
            target.id,
            UserUpdate(role_id=99999),
            admin,
        )

    assert exc.value.status_code == 404
    assert "Role not found" in exc.value.message

def test_update_user_cannot_assign_superadmin(seed_test_db):
    db = seed_test_db

    admin = _user(db, "admin.demo@flowdesk.com")
    target = _user(db, "demo_employee")
    superadmin_role = _role(db, "superadmin")

    with pytest.raises(AppError) as exc:
        users_service.update_user(
            db,
            target.id,
            UserUpdate(role_id=superadmin_role.id),
            admin,
        )

    assert exc.value.status_code == 403
    assert "superadmin" in exc.value.message.lower()

def test_update_user_status(seed_test_db):
    db = seed_test_db

    admin = _user(db, "admin.demo@flowdesk.com")
    target = _user(db, "demo_employee")

    result = users_service.update_user_status(
        db,
        target.id,
        UserStatusUpdate(is_active=False),
        admin,
    )

    assert result.is_active is False
    assert db.commits == 1
    assert result in db.refreshed

def test_update_user_status_activate(seed_test_db):
    db = seed_test_db

    admin = _user(db, "admin.demo@flowdesk.com")
    target = _user(db, "inactive@test.com")

    result = users_service.update_user_status(
        db,
        target.id,
        UserStatusUpdate(is_active=True),
        admin,
    )

    assert result.is_active is True

def test_update_user_status_not_found(seed_test_db):
    db = seed_test_db

    admin = _user(db, "admin.demo@flowdesk.com")

    with pytest.raises(AppError) as exc:
        users_service.update_user_status(
            db,
            uuid4(),
            UserStatusUpdate(is_active=False),
            admin,
        )

    assert exc.value.status_code == 404

def test_update_user_status_cross_company_forbidden(seed_test_db):
    db = seed_test_db

    admin = _user(db, "admin.demo@flowdesk.com")

    other = User(
        username="other",
        email="other2@test.com",
        password="password",
        role_id=_role(db, "employee").id,
        company_id=uuid4(),
        is_active=True,
    )
    other.id = uuid4()
    other.role = _role(db, "employee")

    db.data[User].append(other)

    with pytest.raises(AppError) as exc:
        users_service.update_user_status(
            db,
            other.id,
            UserStatusUpdate(is_active=False),
            admin,
        )

    assert exc.value.status_code == 403

def test_update_superadmin_status_forbidden(seed_test_db):
    db = seed_test_db

    admin = _user(db, "admin.demo@flowdesk.com")
    superadmin = _user(db, "superadmin@test.com")

    with pytest.raises(AppError) as exc:
        users_service.update_user_status(
            db,
            superadmin.id,
            UserStatusUpdate(is_active=False),
            admin,
        )

    assert exc.value.status_code == 403

def test_delete_user(seed_test_db):
    db = seed_test_db

    admin = _user(db, "admin.demo@flowdesk.com")
    target = _user(db, "demo_employee")

    result = users_service.delete_user(
        db,
        target.id,
        admin,
    )

    assert result is None
    assert target.is_active is False
    assert db.commits == 1

def test_delete_user_not_found(seed_test_db):
    db = seed_test_db

    admin = _user(db, "admin.demo@flowdesk.com")

    with pytest.raises(AppError) as exc:
        users_service.delete_user(
            db,
            uuid4(),
            admin,
        )

    assert exc.value.status_code == 404

def test_delete_own_account_forbidden(seed_test_db):
    db = seed_test_db

    admin = _user(db, "admin.demo@flowdesk.com")

    with pytest.raises(AppError) as exc:
        users_service.delete_user(
            db,
            admin.id,
            admin,
        )

    assert exc.value.status_code == 400
    assert "own account" in exc.value.message.lower()

def test_delete_user_cross_company_forbidden(seed_test_db):
    db = seed_test_db

    admin = _user(db, "admin.demo@flowdesk.com")

    other = User(
        username="other_delete",
        email="other_delete@test.com",
        password="password",
        role_id=_role(db, "employee").id,
        company_id=uuid4(),
        is_active=True,
    )
    other.id = uuid4()
    other.role = _role(db, "employee")

    db.data[User].append(other)

    with pytest.raises(AppError) as exc:
        users_service.delete_user(
            db,
            other.id,
            admin,
        )

    assert exc.value.status_code == 403

def test_delete_superadmin_forbidden(seed_test_db):
    db = seed_test_db

    superadmin = _user(db, "superadmin@test.com")
    admin = _user(db, "admin.demo@flowdesk.com")

    with pytest.raises(AppError) as exc:
        users_service.delete_user(
            db,
            superadmin.id,
            admin,
        )

    assert exc.value.status_code == 403

def test_superadmin_can_update_other_company_user(seed_test_db):
    db = seed_test_db

    superadmin = _user(db, "superadmin@test.com")
    target = _user(db, "demo_employee")

    result = users_service.update_user(
        db,
        target.id,
        UserUpdate(username="changed_by_superadmin"),
        superadmin,
    )

    assert result.username == "changed_by_superadmin"

def test_superadmin_can_change_user_status(seed_test_db):
    db = seed_test_db

    superadmin = _user(db, "superadmin@test.com")
    target = _user(db, "demo_employee")

    result = users_service.update_user_status(
        db,
        target.id,
        UserStatusUpdate(is_active=False),
        superadmin,
    )

    assert result.is_active is False

def test_superadmin_can_delete_other_user(seed_test_db):
    db = seed_test_db

    superadmin = _user(db, "superadmin@test.com")
    target = _user(db, "demo_employee")

    users_service.delete_user(
        db,
        target.id,
        superadmin,
    )

    assert target.is_active is False