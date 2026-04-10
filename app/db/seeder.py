from sqlalchemy.orm import Session
from app.models.roles import Role

DEFAULT_ROLES = [
    {"name": "admin",     "description": "Full access, manages users and company settings"},
    {"name": "manager",   "description": "Can manage employees and view reports"},
    {"name": "employee",  "description": "Basic access"},
]

def seed_roles(db: Session):
    for role_data in DEFAULT_ROLES:
        exists = db.query(Role).filter(Role.name == role_data["name"]).first()
        if not exists:
            db.add(Role(**role_data))
    db.commit()