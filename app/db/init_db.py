from sqlalchemy import text
from app.models.roles import Role
from app.models.users import User
from app.db.seeder import seed_roles, seed_superadmin
from app.models.companies import Company
from app.core.database import engine, SessionLocal

def init_db():
    with engine.connect() as conn:
        conn.execute(text('CREATE SCHEMA IF NOT EXISTS "global"'))
        conn.commit()

    from app.core.database import Base
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        seed_roles(db)
        seed_superadmin(db)
    finally:
        db.close()