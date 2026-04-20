from sqlalchemy.orm import Session

from app.models.permissions import Permission
from app.models.roles import Role
from app.models.users import User
from app.core.security import hash_password
from app.core.config import SUPERADMIN_EMAIL, SUPERADMIN_USERNAME, SUPERADMIN_PASSWORD

DEFAULT_ROLES = [
    {"name": "superadmin", "description": "Full access to all companies and settings"},
    {"name": "admin",     "description": "Full access, manages users and company settings"},
    {"name": "manager",   "description": "Can manage employees and view reports"},
    {"name": "employee",  "description": "Basic access"},
]

DEFAULT_PERMISSIONS = [ 
    {"name": "view_inventory"},
    {"name": "edit_inventory"},
    {"name": "view_sales"},
    {"name": "edit_sales"},
    {"name": "create_movements"},
    {"name": "view_movements"},
    {"name": "create_users"}
]

def seed_roles(db: Session):
    for role_data in DEFAULT_ROLES:
        exists = db.query(Role).filter(Role.name == role_data["name"]).first()
        if not exists:
            db.add(Role(**role_data))
    db.commit()

def seed_superadmin(db: Session):
    exists = db.query(User).filter(User.email == SUPERADMIN_EMAIL).first()
    if exists:
        return

    superadmin_role = db.query(Role).filter(Role.name == "superadmin").first()
    if not superadmin_role:
        raise Exception("Superadmin role not found — run seed_roles first")

    superadmin = User(
        username=SUPERADMIN_USERNAME,
        email=SUPERADMIN_EMAIL,
        password=hash_password(SUPERADMIN_PASSWORD),
        role_id=superadmin_role.id,
        company_id=None,  # superadmin belongs to no company
        is_active=True,
    )
    db.add(superadmin)
    db.commit()

def seed_permissions(db: Session):
    for perm_data in DEFAULT_PERMISSIONS:
        exists = db.query(Permission).filter(
            Permission.name == perm_data["name"]
        ).first()

        if not exists:
            db.add(Permission(**perm_data))

    db.commit()

