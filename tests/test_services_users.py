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

    assert exc.value.status_code == 404

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

    assert exc.value.status_code == 404

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

    assert exc.value.status_code == 404

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

def test_update_own_role_forbidden(seed_test_db):
    db = seed_test_db

    admin = _user(db, "admin.demo@flowdesk.com")
    admin_role_id = admin.role_id

    with pytest.raises(AppError) as exc:
        users_service.update_user(
            db,
            admin.id,
            UserUpdate(role_id=_role(db, "employee").id),
            admin,
        )

    assert exc.value.status_code == 400
    assert exc.value.message == "Cannot change your own role"
    assert admin.role_id == admin_role_id
    assert db.commits == 0

def test_update_own_username_allowed(seed_test_db):
    db = seed_test_db

    admin = _user(db, "admin.demo@flowdesk.com")

    result = users_service.update_user(
        db,
        admin.id,
        UserUpdate(username="admin_renamed", role_id=admin.role_id),
        admin,
    )

    assert result.username == "admin_renamed"

def test_update_user_role_and_status_in_one_commit(seed_test_db):
    db = seed_test_db

    admin = _user(db, "admin.demo@flowdesk.com")
    target = _user(db, "demo_employee")
    manager_role = _role(db, "manager")

    result = users_service.update_user(
        db,
        target.id,
        UserUpdate(username="employee_moved", role_id=manager_role.id, is_active=False),
        admin,
    )

    assert result.username == "employee_moved"
    assert result.role_id == manager_role.id
    assert result.is_active is False
    assert db.commits == 1

def test_update_own_status_through_put_forbidden(seed_test_db):
    db = seed_test_db

    admin = _user(db, "admin.demo@flowdesk.com")

    with pytest.raises(AppError) as exc:
        users_service.update_user(
            db,
            admin.id,
            UserUpdate(username="admin_renamed", is_active=False),
            admin,
        )

    assert exc.value.status_code == 400
    assert exc.value.message == "Cannot change your own status"
    assert admin.username == "demo_admin"
    assert admin.is_active is True
    assert db.commits == 0

def test_update_user_refused_role_leaves_other_fields_unchanged(seed_test_db):
    db = seed_test_db

    admin = _user(db, "admin.demo@flowdesk.com")
    target = _user(db, "demo_employee")

    with pytest.raises(AppError) as exc:
        users_service.update_user(
            db,
            target.id,
            UserUpdate(username="must_not_apply", role_id=999999, is_active=False),
            admin,
        )

    assert exc.value.status_code == 404
    assert target.username == "demo_employee"
    assert target.is_active is True
    assert db.commits == 0

def test_put_user_endpoint_applies_status_with_role(seed_test_db, admin_client):
    target = _user(seed_test_db, "demo_employee")
    manager_role = _role(seed_test_db, "manager")

    response = admin_client.put(
        f"/api/v1/users/{target.id}",
        json={"role_id": manager_role.id, "is_active": False},
    )

    assert response.status_code == 200
    assert response.json()["role_id"] == manager_role.id
    assert response.json()["is_active"] is False
    assert seed_test_db.commits == 1

def test_put_user_endpoint_refuses_own_role_change(seed_test_db, admin_client):
    admin = _user(seed_test_db, "admin.demo@flowdesk.com")

    response = admin_client.put(
        f"/api/v1/users/{admin.id}",
        json={"role_id": _role(seed_test_db, "employee").id},
    )

    assert response.status_code == 400
    assert response.json()["message"] == "Cannot change your own role"
