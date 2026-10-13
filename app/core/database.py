from urllib.parse import quote_plus
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from app.core.config import (
    DB_HOST, DB_NAME, DB_USER, DB_PASSWORD, DB_PORT,
    DB_POOL_SIZE, DB_MAX_OVERFLOW, DB_POOL_TIMEOUT, DB_POOL_RECYCLE,
)


Base = declarative_base()
SessionLocal = sessionmaker(autocommit=False, autoflush=False)
_engine = None

def _build_engine():
    user_enc = quote_plus(DB_USER or "")
    pwd_enc  = quote_plus(DB_PASSWORD or "")

    connection_url = (
        f"postgresql+psycopg2://{user_enc}:{pwd_enc}"
        f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    )

    return create_engine(
        connection_url,
        pool_pre_ping=True,
        pool_size=DB_POOL_SIZE,
        max_overflow=DB_MAX_OVERFLOW,
        pool_timeout=DB_POOL_TIMEOUT,
        pool_recycle=DB_POOL_RECYCLE,
        echo=False
    )


def get_engine():
    global _engine
    if _engine is None:
        _engine = _build_engine()
        SessionLocal.configure(bind=_engine)
    return _engine
