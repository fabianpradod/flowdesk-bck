
import os

# Configuration must be in place before any app module is imported, because
# app.core.config reads the environment at import time.
os.environ.setdefault("DB_SERVER", "localhost")
os.environ.setdefault("DB_PORT", "5433")
os.environ.setdefault("DB_DATABASE", "flowdesk_test")
os.environ.setdefault("DB_USERNAME", "flowdesk")
os.environ.setdefault("DB_PASSWORD", "flowdesk")
os.environ.setdefault("SECRET_KEY", "integration-tests-only-secret-key-0123456789")
os.environ.setdefault("SUPERADMIN_EMAIL", "superadmin@integration.test")
os.environ.setdefault("SUPERADMIN_PASSWORD", "Superadmin12345!")
os.environ.setdefault("SUPERADMIN_USERNAME", "superadmin")
os.environ.setdefault("DEMO_USER_PASSWORD", "Demo12345!")
os.environ["DEMO_SEED_ENABLED"] = "true"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

def _database_reachable() -> tuple[bool, str]:
    from app.core.database import get_engine

    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, ""
    except Exception as exc:  
        return False, str(exc).splitlines()[0]


@pytest.fixture(scope="session")
def app():
    reachable, reason = _database_reachable()
    if not reachable:
        message = f"PostgreSQL is not reachable for integration tests: {reason}"
        if os.getenv("INTEGRATION_REQUIRE_DB") == "1":
            pytest.fail(message)
        pytest.skip(message)

    import main  
    return main.app


@pytest.fixture(scope="session")
def client(app):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def db(app):
    """A separate session used only to verify what the API persisted."""
    from app.core.database import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="session")
def tenant_tables(app):
    from app.core.database import SessionLocal
    from app.models.companies import Company
    from app.tenancy.runtime import get_tenant_tables

    session = SessionLocal()
    try:
        company = session.query(Company).filter(Company.name == "Flowdesk Demo").one()
        return get_tenant_tables(company.schema_name)
    finally:
        session.close()
