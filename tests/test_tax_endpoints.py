from types import SimpleNamespace
from uuid import uuid4
from decimal import Decimal
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.dependencies.auth import get_current_user, get_db
from app.api.v1.routes.commercial import router
import app.services.commercial as commercial_service

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

def test_tax_configuration_get_serializes_the_configured_rate(monkeypatch):
    monkeypatch.setattr(
        commercial_service,
        "get_tax_configuration",
        lambda *_args: {"tasa_impuesto": Decimal("15.00")},
    )

    response = _client("employee").get("/api/v1/commercial/tax-configuration")

    assert response.status_code == 200
    assert response.json() == {"tasa_impuesto": "15.00"}

def test_tax_configuration_put_returns_the_persisted_rate(monkeypatch):
    received = {}

    def update(data, *_args):
        received["rate"] = data.tasa_impuesto
        return {"tasa_impuesto": Decimal("15.00")}

    monkeypatch.setattr(commercial_service, "update_tax_configuration", update)

    response = _client("admin").put(
        "/api/v1/commercial/tax-configuration", json={"tasa_impuesto": "15.00"}
    )

    assert response.status_code == 200
    assert received["rate"] == Decimal("15.00")
    assert response.json() == {"tasa_impuesto": "15.00"}