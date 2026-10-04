"""Sprint regression smoke tests for previously existing API modules.

These tests intentionally exercise representative legacy endpoints after the
authorization and chatbot changes. They do not replace the complete regression
suite; they provide a fast gate for the sprint.
"""

import app.services.inventory as inventory_service
import app.services.commercial as commercial_service

def test_public_endpoints_remain_available(client):
    root = client.get("/")
    health = client.get("/health")

    assert root.status_code == 200
    assert root.json() == {"message": "Flowdesk API"}
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

def test_inventory_read_endpoints_remain_available_for_authenticated_employee(employee_client, monkeypatch):
    monkeypatch.setattr(inventory_service, "list_products", lambda *a, **k: [])
    monkeypatch.setattr(inventory_service, "list_suppliers", lambda *a, **k: [])
    monkeypatch.setattr(inventory_service, "list_inventory_alerts", lambda *a, **k: [])
    products = employee_client.get("/api/v1/inventory/products")
    suppliers = employee_client.get("/api/v1/inventory/suppliers")
    alerts = employee_client.get("/api/v1/inventory/alerts")

    assert products.status_code == 200
    assert suppliers.status_code == 200
    assert alerts.status_code == 200

def test_commercial_read_endpoints_remain_available_for_authenticated_employee(employee_client, monkeypatch):
    monkeypatch.setattr(commercial_service, "list_clients", lambda *a, **k: [])
    monkeypatch.setattr(commercial_service, "get_tax_configuration", lambda *a, **k: {"tasa_impuesto": 0})
    clients = employee_client.get("/api/v1/commercial/clients")
    tax = employee_client.get("/api/v1/commercial/tax-configuration")

    assert clients.status_code == 200
    assert tax.status_code == 200

def test_admin_role_endpoint_remains_available_after_authorization_changes(admin_client):
    response = admin_client.get("/api/v1/roles")

    assert response.status_code == 200
    assert {role["name"] for role in response.json()} == {
        "superadmin", "admin", "manager", "employee"
    }