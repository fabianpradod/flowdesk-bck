from sqlalchemy import text
from app.models.roles import Role
from app.models.users import User
from app.db.seeder import seed_demo_data, seed_roles, seed_superadmin
from app.models.companies import Company
from app.core.config import DEMO_SEED_ENABLED
from app.core.database import Base, SessionLocal, get_engine

def init_db():
    engine = get_engine()
    with engine.connect() as conn:
        conn.execute(text('CREATE SCHEMA IF NOT EXISTS "global"'))
        conn.commit()

    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        seed_roles(db)
        seed_superadmin(db)
        if DEMO_SEED_ENABLED:
            seed_demo_data(db)
    finally:
        db.close()
