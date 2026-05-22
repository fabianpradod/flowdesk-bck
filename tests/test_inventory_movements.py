from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_insufficient_stock():
    token = "admin-token"

    response = client.post(
        "/api/v1/inventory/movements",
        headers={
            "Authorization": f"Bearer {token}"
        },
        json={
            "product_id": 1,
            "quantity": 99999,
            "movement_type": "OUT"
        }
    )
    assert response.status_code == 400

def test_inventory_movement_success():
    token = "admin-token"

    response = client.post(
        "/api/v1/inventory/movements",
        headers={
            "Authorization": f"Bearer {token}"
        },
        json={
            "product_id": 1,
            "quantity": 1,
            "movement_type": "OUT"
        }
    )
    assert response.status_code in [200, 201]

def test_inventory_product_not_found():
    token = "admin-token"

    response = client.post(
        "/api/v1/inventory/movements",
        headers={
            "Authorization": f"Bearer {token}"
        },
        json={
            "product_id": 999999,
            "quantity": 1,
            "movement_type": "OUT"
        }
    )
    assert response.status_code in [400, 404]

def test_invalid_inventory_quantity():
    token = "admin-token"

    response = client.post(
        "/api/v1/inventory/movements",
        headers={
            "Authorization": f"Bearer {token}"
        },
        json={
            "product_id": 1,
            "quantity": -5,
            "movement_type": "OUT"
        }
    )
    assert response.status_code == 400

def test_excessive_quantity(client):
    token = "admin-token"

    response = client.post(
        "/api/v1/inventory/movements",
        headers={
            "Authorization": f"Bearer {token}"
        },
        json={
            "product_id": 1,
            "quantity": 999999999999999,
            "movement_type": "OUT"
        }
    )
    assert response.status_code == 400