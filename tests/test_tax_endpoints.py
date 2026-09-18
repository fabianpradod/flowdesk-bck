from types import SimpleNamespace
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.dependencies.auth import get_current_user, get_db
from app.api.v1.routes.commercial import router

def _client(role: str | None):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: SimpleNamespace()
    if role is not None:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=uuid4(),
            company_id=uuid4(),
            company=SimpleNamespace(is_active=True, schema_name="tenant_" + "c" * 32),
            role=SimpleNamespace(name=role),
        )
    return TestClient(app, raise_server_exceptions=False)

def test_tax_configuration_endpoint_requires_authentication():
    assert _client(None).get("/api/v1/commercial/tax-configuration").status_code == 401

def test_tax_configuration_update_rejects_manager_before_service():
    response = _client("manager").put(
        "/api/v1/commercial/tax-configuration", json={"tasa_impuesto": "13.00"}
    )

    assert response.status_code == 403

def test_tax_configuration_update_rejects_invalid_rate_before_service():
    response = _client("admin").put(
        "/api/v1/commercial/tax-configuration", json={"tasa_impuesto": "101.00"}
    )

    assert response.status_code == 422