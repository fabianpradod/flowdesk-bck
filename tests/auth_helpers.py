from uuid import uuid4
from types import SimpleNamespace

def admin_user():
    return SimpleNamespace(
        id = uuid4(),
        username = "admin",
        email = "admin@test.com",
        company_id = uuid4(),
        is_active = True,
        role = SimpleNamespace(
            id = 2,
            name = "admin"
        )
    )

def superadmin_user():
    return SimpleNamespace(
        id = uuid4(),
        username = "superadmin",
        email = "super@test.com",
        company_id = None,
        is_active = True,
        role = SimpleNamespace(
            id = 1,
            name = "superadmin"
        )
    )

def employee_user():
    return SimpleNamespace(
        id = uuid4(),
        username = "employee",
        email = "employee@test.com",
        company_id = uuid4(),
        is_active = True,
        role = SimpleNamespace(
            id = 4,
            name = "employee"
        )
    )