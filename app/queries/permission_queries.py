from sqlalchemy.orm import Session
from app.models.permissions import Permission

def get_permissions_by_names(db: Session, names: list):
    return db.query(Permission).filter(Permission.name.in_(names)).all()