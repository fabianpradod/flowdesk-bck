from uuid import uuid4
from app.models.companies import Company
from app.models.roles import Role
from app.models.users import User

def test_company_model():
    company = Company(
        name = "Empresa Demo",
        schema_name = "tenant_demo",
    )

    assert company.name == "Empresa Demo"
    assert company.schema_name == "tenant_demo"

def test_role_model():
    role = Role(
        name = "admin",
        description = "Administrador",
    )

    assert role.name == "admin"
    assert role.description == "Administrador"

def test_user_model():
    user = User(
        username = "john",
        email = "john@test.com",
        password = "hash",
        role_id = 1,
        company_id = uuid4(),
    )

    assert user.username == "john"
    assert user.email == "john@test.com"
    assert user.role_id == 1