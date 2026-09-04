from uuid import uuid4
import pytest
from app.services import inventory as inventory_service

PRODUCT_ID = uuid4()
START_DATE = "2026-08-01"
END_DATE = "2026-08-31"

def _point():
    return {
        "period_start": START_DATE,
        "period_label": "2026-08",
        "inbound_quantity": "12.00",
        "outbound_quantity": "5.00",
        "net_quantity": "7.00",
        "movement_count": 3,
        "ending_stock": "21.00",
    }

@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/inventory/analytics/monthly",
        "/api/v1/inventory/analytics/trend",
        "/api/v1/inventory/analytics/products",
        "/api/v1/inventory/metrics",
    ],
)
def test_advanced_analytics_require_authentication(client, path):
    assert client.get(path).status_code == 401

def test_monthly_analytics_forwards_custom_filters(admin_client, monkeypatch):
    captured = {}

    def fake_service(_user, _db, **filters):
        captured.update(filters)
        point = _point() | {
            "previous_net_quantity": "4.00",
            "net_change_quantity": "3.00",
            "net_change_percent": "75.00",
        }
        return {
            "period": "custom",
            "product_id": PRODUCT_ID,
            "start_date": START_DATE,
            "end_date": END_DATE,
            "points": [point],
        }

    monkeypatch.setattr(inventory_service, "get_monthly_behavior", fake_service)
    response = admin_client.get(
        "/api/v1/inventory/analytics/monthly",
        params={
            "period": "custom",
            "product_id": str(PRODUCT_ID),
            "start_date": START_DATE,
            "end_date": END_DATE,
        },
    )

    assert response.status_code == 200
    assert captured["period"] == "custom"
    assert captured["product_id"] == PRODUCT_ID
    assert captured["start_date"].isoformat() == START_DATE
    assert response.json()["points"][0]["net_change_percent"] == "75.00"

def test_trend_analytics_forwards_window_and_filters(admin_client, monkeypatch):
    captured = {}

    def fake_service(_user, _db, **filters):
        captured.update(filters)
        return {
            "period": "30d",
            "window": "week",
            "product_id": PRODUCT_ID,
            "start_date": START_DATE,
            "end_date": END_DATE,
            "points": [_point()],
        }

    monkeypatch.setattr(inventory_service, "get_inventory_trend", fake_service)
    response = admin_client.get(
        "/api/v1/inventory/analytics/trend",
        params={"period": "30d", "window": "week", "product_id": str(PRODUCT_ID)},
    )

    assert response.status_code == 200
    assert captured["window"] == "week"
    assert captured["product_id"] == PRODUCT_ID
    assert response.json()["points"][0]["net_quantity"] == "7.00"

def test_product_analytics_forwards_sort_limit_and_dates(admin_client, monkeypatch):
    captured = {}

    def fake_service(_user, _db, **filters):
        captured.update(filters)
        return {
            "period": "custom",
            "sort_by": "stock_risk",
            "start_date": START_DATE,
            "end_date": END_DATE,
            "products": [
                {
                    "product_id": PRODUCT_ID,
                    "sku": "SKU-1",
                    "nombre": "Producto crítico",
                    "inbound_quantity": "12.00",
                    "outbound_quantity": "5.00",
                    "net_quantity": "7.00",
                    "movement_count": 3,
                    "ending_stock": "1.00",
                    "stock_minimo": "10.00",
                    "stock_risk_score": "90.00",
                }
            ],
        }

    monkeypatch.setattr(inventory_service, "get_product_analytics", fake_service)
    response = admin_client.get(
        "/api/v1/inventory/analytics/products",
        params={
            "period": "custom",
            "sort_by": "stock_risk",
            "limit": 5,
            "start_date": START_DATE,
            "end_date": END_DATE,
        },
    )

    assert response.status_code == 200
    assert captured["sort_by"] == "stock_risk"
    assert captured["limit"] == 5
    assert captured["end_date"].isoformat() == END_DATE
    assert response.json()["products"][0]["stock_risk_score"] == "90.00"

def test_metrics_forwards_product_and_date_filters(admin_client, monkeypatch):
    captured = {}

    def fake_service(_user, _db, **filters):
        captured.update(filters)
        return {
            "period": "custom",
            "product_id": PRODUCT_ID,
            "start_date": START_DATE,
            "end_date": END_DATE,
            "entradas": "12.00",
            "salidas": "5.00",
            "stock_bajo": 2,
            "sin_stock": 1,
        }

    monkeypatch.setattr(inventory_service, "get_inventory_metrics", fake_service)
    response = admin_client.get(
        "/api/v1/inventory/metrics",
        params={
            "period": "custom",
            "product_id": str(PRODUCT_ID),
            "start_date": START_DATE,
            "end_date": END_DATE,
        },
    )

    assert response.status_code == 200
    assert captured["product_id"] == PRODUCT_ID
    assert response.json()["sin_stock"] == 1

@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/v1/inventory/analytics/monthly", {"period": "invalid"}),
        ("/api/v1/inventory/analytics/trend", {"window": "year"}),
        ("/api/v1/inventory/analytics/products", {"sort_by": "unknown"}),
        ("/api/v1/inventory/analytics/products", {"limit": 0}),
        ("/api/v1/inventory/analytics/products", {"limit": 51}),
        ("/api/v1/inventory/metrics", {"product_id": "not-a-uuid"}),
    ],
)
def test_advanced_analytics_reject_invalid_filters(admin_client, path, params):
    response = admin_client.get(path, params=params)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"