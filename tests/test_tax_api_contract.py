"""HTTP contract smoke tests for the frontend-facing taxation API."""

from datetime import date
from types import SimpleNamespace
from uuid import uuid4
from fastapi import FastAPI
from main import app
from fastapi.testclient import TestClient
from app.api.dependencies.auth import get_current_user, get_db
from app.api.v1.routes import taxation

def _contract_client(monkeypatch):
    app = FastAPI()
    app.include_router(taxation.router)
    user = SimpleNamespace(
        id=uuid4(),
        company_id=uuid4(),
        company=SimpleNamespace(is_active=True, schema_name="tenant_contract"),
        role=SimpleNamespace(name="admin"),
    )
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: SimpleNamespace()
    batch_id = uuid4()
    mapping_id = uuid4()
    monkeypatch.setattr(taxation.service, "get_tax_profile", lambda *_: {"profiles": []})
    monkeypatch.setattr(taxation.service, "put_tax_profile", lambda data, *_: {"profiles": [data.model_dump(mode="json")]})
    monkeypatch.setattr(taxation.service, "validate_tax_profile", lambda *_: {
        "valid": True, "errors": [], "warnings": [], "information": [],
    })
    monkeypatch.setattr(taxation.service, "calculate_tax", lambda *_: {
        "tax_debit": "10.00", "tax_credit": "2.00", "net_tax": "8.00",
        "tax_payable": "8.00", "carry_forward": "0.00", "withholding_tax": "0.00", "details": [],
    })
    monkeypatch.setattr(taxation.imports, "create_mapping", lambda *_: {"id": mapping_id, "name": "contract"})
    monkeypatch.setattr(taxation.imports, "list_mappings", lambda *_: [])
    monkeypatch.setattr(taxation.imports, "upload", lambda *_: {"id": batch_id, "status": "UPLOADED"})
    monkeypatch.setattr(taxation.imports, "preview", lambda *_: {
        "rows_detected": 1, "rows_valid": 1, "rows_invalid": 0,
        "headers": ["Date"], "sample_rows": [], "normalized_samples": [],
        "errors": [], "warnings": [], "suggested_mappings": [],
        "mapped_fields": [], "unmapped_columns": [], "duplicate_candidates": [], "rows": [],
    })
    monkeypatch.setattr(taxation.imports, "validate_batch", lambda *_: {"status": "VALIDATED", "errors": [], "warnings": []})
    monkeypatch.setattr(taxation.imports, "execute", lambda *_: {
        "status": "IMPORTED", "total": 1, "imported": 1, "failed": [], "duplicates": [], "warnings": [],
    })
    monkeypatch.setattr(taxation.tax_period, "calculate_period", lambda *_args, **_kwargs: {
        "period": {"start": date(2026, 1, 1), "end": date(2026, 1, 31)},
        "tax_debit": "10.00", "tax_credit": "2.00", "net_tax": "8.00",
        "tax_payable": "8.00", "carry_forward": "0.00", "withholding_tax": "0.00",
        "input_documents_count": 0, "input_tax_components_count": 0,
        "eligible_tax_components_count": 0, "currency": "USD", "details": [],
    })

    return TestClient(app), batch_id, mapping_id

def test_frontend_can_follow_tax_configuration_simulation_and_import_flow(monkeypatch):
    client, batch_id, mapping_id = _contract_client(monkeypatch)
    profile = {"name": "Frontend profile", "effective_from": "2026-01-01", "taxes": [], "rules": []}

    assert client.get("/api/v1/tax/profile").status_code == 200
    assert client.put("/api/v1/tax/profile", json=profile).status_code == 200
    assert client.post("/api/v1/tax/profile/validate", json=profile).json()["valid"] is True
    assert client.post("/api/v1/tax/calculate", json={"as_of": "2026-01-01", "operations": []}).status_code == 200
    assert client.post("/api/v1/tax/import-mappings", json={
        "name": "contract", "source_type": "CSV", "mapping": {"Date": "issue_date"},
    }).status_code == 201

    upload = client.post(
        "/api/v1/tax/imports",
        files={"file": ("contract.csv", b"Date\n2026-01-01\n", "text/csv")},
    )

    assert upload.status_code == 201
    assert client.post(f"/api/v1/tax/imports/{batch_id}/preview", json={"mapping_id": str(mapping_id)}).status_code == 200
    assert client.post(f"/api/v1/tax/imports/{batch_id}/validate", json={"mapping_id": str(mapping_id)}).json()["status"] == "VALIDATED"
    assert client.post(f"/api/v1/tax/imports/{batch_id}/execute", json={"mapping_id": str(mapping_id)}).json()["status"] == "IMPORTED"

    period = client.post("/api/v1/tax/period/calculate", json={"start_date": "2026-01-01", "end_date": "2026-01-31"})

    assert period.status_code == 200
    assert period.json()["tax_payable"] == "8.00"

def test_tax_openapi_exposes_typed_calculation_contract_and_no_tenant_selector(monkeypatch):
    client, _, _ = _contract_client(monkeypatch)
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]

    assert "/api/v1/tax/profile" in paths
    assert "/api/v1/tax/calculate" in paths
    assert "/api/v1/tax/period/calculate" in paths
    assert "/api/v1/tax/imports/{batch_id}/preview" in paths
    assert "TaxCalculationResponse" in schema["components"]["schemas"]
    assert "TaxPeriodCalculationResponse" in schema["components"]["schemas"]

    request_schema = schema["components"]["schemas"]["TaxCalculationRequest"]["properties"]

    assert "tenant_id" not in request_schema
    assert "company_id" not in request_schema
    assert "schema_name" not in request_schema

def test_tax_cors_allows_configured_local_frontend(monkeypatch):
    response = TestClient(app).options(
        "/api/v1/tax/profile",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"