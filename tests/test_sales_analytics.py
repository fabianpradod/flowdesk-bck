from datetime import datetime
from decimal import Decimal
from uuid import uuid4
import pytest
from sqlalchemy import Boolean, Column, DateTime, MetaData, Numeric, String, Table, create_engine, insert
from sqlalchemy.orm import sessionmaker
from app.services import analytics as analytics_service
from app.utils.exceptions import AppError
from main import app

@pytest.fixture
def analytics_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    metadata = MetaData()
    sales = Table(
        "venta",
        metadata,
        Column("id", String, primary_key=True),
        Column("fecha", DateTime, nullable=False),
        Column("subtotal", Numeric(10, 2), nullable=False),
        Column("descuento", Numeric(10, 2), nullable=False),
        Column("impuesto", Numeric(10, 2), nullable=False),
        Column("total", Numeric(10, 2), nullable=False),
        Column("cliente_id", String, nullable=True),
        Column("estado", String, nullable=False),
    )
    products = Table(
        "producto",
        metadata,
        Column("id", String, primary_key=True),
        Column("proveedor_id", String, nullable=True),
        Column("sku", String, nullable=True),
        Column("nombre", String, nullable=True),
        Column("created_at", DateTime, nullable=True),
        Column("stock_actual", Numeric(12, 2), nullable=False),
        Column("stock_minimo", Numeric(12, 2), nullable=False),
        Column("is_active", Boolean, nullable=False),
    )
    movements = Table(
        "movimiento_inventario",
        metadata,
        Column("id", String, primary_key=True),
        Column("producto_id", String, nullable=False),
        Column("tipo_movimiento", String, nullable=False),
        Column("fecha", DateTime, nullable=False),
        Column("cantidad", Numeric(12, 2), nullable=False),
    )
    sale_details = Table(
        "detalle_venta",
        metadata,
        Column("id", String, primary_key=True),
        Column("venta_id", String, nullable=False),
        Column("producto_id", String, nullable=False),
        Column("cantidad", Numeric(12, 2), nullable=False),
        Column("subtotal", Numeric(10, 2), nullable=False),
    )
    metadata.create_all(engine)
    db = sessionmaker(bind=engine, future=True)()
    monkeypatch.setattr(
        analytics_service,
        "_analytics_tables",
        lambda _user: {
            "venta": sales,
            "producto": products,
            "movimiento_inventario": movements,
            "detalle_venta": sale_details,
        },
    )
    yield db, sales, products, movements
    db.close()
    engine.dispose()

def _sale(sales, *, day, total, client_id=None, state="completada"):
    total = Decimal(str(total))
    return insert(sales).values(
        id=str(uuid4()),
        fecha=datetime(2026, 8, day, 12),
        subtotal=total,
        descuento=Decimal("2.00"),
        impuesto=Decimal("1.00"),
        total=total - Decimal("1.00"),
        cliente_id=client_id,
        estado=state,
    )

def test_sales_metrics_count_only_finalized_sales(analytics_db):
    db, sales, _products, _movements = analytics_db
    client_id = str(uuid4())
    db.execute(_sale(sales, day=2, total=100, client_id=client_id, state="Completada"))
    db.execute(_sale(sales, day=3, total=50, state="pagada"))
    db.execute(_sale(sales, day=4, total=900, state="borrador"))
    db.execute(_sale(sales, day=5, total=800, state="cancelada"))
    db.commit()

    result = analytics_service.get_sales_metrics(
        object(),
        db,
        period="custom",
        start_date=datetime(2026, 8, 1).date(),
        end_date=datetime(2026, 8, 31).date(),
    )

    assert result["sales_count"] == 2
    assert result["gross_sales"] == Decimal("150.00")
    assert result["net_sales"] == Decimal("148.00")
    assert result["average_ticket"] == Decimal("74.00")
    assert result["registered_customer_sales"] == 1
    assert result["final_consumer_sales"] == 1

def test_sales_metrics_filter_final_consumer(analytics_db):
    db, sales, _products, _movements = analytics_db
    db.execute(_sale(sales, day=2, total=100, client_id=str(uuid4())))
    db.execute(_sale(sales, day=3, total=50))
    db.commit()

    result = analytics_service.get_sales_metrics(
        object(),
        db,
        period="custom",
        customer_type="final_consumer",
        start_date=datetime(2026, 8, 1).date(),
        end_date=datetime(2026, 8, 31).date(),
    )

    assert result["sales_count"] == 1
    assert result["final_consumer_sales"] == 1
    assert result["net_sales"] == Decimal("49.00")

def test_sales_trend_groups_by_week(analytics_db):
    db, sales, _products, _movements = analytics_db
    db.execute(_sale(sales, day=3, total=40))
    db.execute(_sale(sales, day=5, total=60))
    db.execute(_sale(sales, day=12, total=20))
    db.commit()

    result = analytics_service.get_sales_trend(
        object(),
        db,
        period="custom",
        window="week",
        start_date=datetime(2026, 8, 1).date(),
        end_date=datetime(2026, 8, 31).date(),
    )

    assert [point["sales_count"] for point in result["points"]] == [2, 1]
    assert result["points"][0]["gross_sales"] == Decimal("100.00")
    assert result["points"][0]["period_start"].weekday() == 0

def test_sales_filters_reject_client_with_final_consumer():
    with pytest.raises(AppError) as error:
        analytics_service._fetch_final_sales(
            object(),
            object(),
            analytics_range={},
            customer_type="final_consumer",
            client_id=uuid4(),
        )

    assert error.value.status_code == 400

def test_risk_distribution_uses_stock_and_sales_demand(analytics_db):
    db, _sales, products, movements = analytics_db
    critical_id, medium_id, healthy_id = (str(uuid4()) for _ in range(3))
    db.execute(
        insert(products),
        [
            {"id": critical_id, "stock_actual": 0, "stock_minimo": 10, "is_active": True},
            {"id": medium_id, "stock_actual": 5, "stock_minimo": 10, "is_active": True},
            {"id": healthy_id, "stock_actual": 20, "stock_minimo": 10, "is_active": True},
            {"id": str(uuid4()), "stock_actual": 0, "stock_minimo": 10, "is_active": False},
        ],
    )
    db.execute(
        insert(movements).values(
            id=str(uuid4()),
            producto_id=critical_id,
            tipo_movimiento="salida_venta",
            fecha=datetime(2026, 8, 10),
            cantidad=10,
        )
    )
    db.commit()

    result = analytics_service.get_inventory_risk_distribution(
        object(),
        db,
        period="custom",
        start_date=datetime(2026, 8, 1).date(),
        end_date=datetime(2026, 8, 31).date(),
    )
    counts = {bucket["level"]: bucket["product_count"] for bucket in result["distribution"]}

    assert result["total_products"] == 3
    assert counts == {"critical": 1, "high": 0, "medium": 1, "low": 0, "healthy": 1}
    assert sum(bucket["percentage"] for bucket in result["distribution"]) == Decimal("100.00")

def test_top_selling_products_uses_finalized_sale_details(analytics_db):
    db, sales, products, _movements = analytics_db
    details = products.metadata.tables["detalle_venta"]
    product_a, product_b = str(uuid4()), str(uuid4())
    sale_a, sale_b, draft_sale = str(uuid4()), str(uuid4()), str(uuid4())
    db.execute(
        insert(products),
        [
            {"id": product_a, "sku": "A", "nombre": "Arroz", "stock_actual": 1, "stock_minimo": 1, "is_active": True},
            {"id": product_b, "sku": "B", "nombre": "Frijol", "stock_actual": 1, "stock_minimo": 1, "is_active": True},
        ],
    )
    db.execute(
        insert(sales),
        [
            {"id": sale_a, "fecha": datetime(2026, 8, 2), "subtotal": 20, "descuento": 0, "impuesto": 0, "total": 20, "estado": "completada"},
            {"id": sale_b, "fecha": datetime(2026, 8, 3), "subtotal": 15, "descuento": 0, "impuesto": 0, "total": 15, "estado": "pagada"},
            {"id": draft_sale, "fecha": datetime(2026, 8, 4), "subtotal": 999, "descuento": 0, "impuesto": 0, "total": 999, "estado": "borrador"},
        ],
    )
    db.execute(
        insert(details),
        [
            {"id": str(uuid4()), "venta_id": sale_a, "producto_id": product_a, "cantidad": 2, "subtotal": 20},
            {"id": str(uuid4()), "venta_id": sale_b, "producto_id": product_b, "cantidad": 1, "subtotal": 15},
            {"id": str(uuid4()), "venta_id": draft_sale, "producto_id": product_b, "cantidad": 50, "subtotal": 999},
        ],
    )
    db.commit()

    result = analytics_service.get_top_selling_products(
        object(), db, period="custom", start_date=datetime(2026, 8, 1).date(), end_date=datetime(2026, 8, 31).date()
    )

    assert [item["sku"] for item in result["products"]] == ["A", "B"]
    assert result["products"][0]["units_sold"] == Decimal("2")
    assert result["products"][0]["revenue"] == Decimal("20.00")

def test_product_creation_trend_groups_status_by_week(analytics_db):
    db, _sales, products, _movements = analytics_db
    db.execute(
        insert(products),
        [
            {"id": str(uuid4()), "created_at": datetime(2026, 8, 3), "stock_actual": 1, "stock_minimo": 1, "is_active": True},
            {"id": str(uuid4()), "created_at": datetime(2026, 8, 5), "stock_actual": 1, "stock_minimo": 1, "is_active": False},
            {"id": str(uuid4()), "created_at": datetime(2026, 8, 12), "stock_actual": 1, "stock_minimo": 1, "is_active": True},
        ],
    )
    db.commit()

    result = analytics_service.get_product_creation_trend(
        object(), db, period="custom", window="week", start_date=datetime(2026, 8, 1).date(), end_date=datetime(2026, 8, 31).date()
    )

    assert result["total_created"] == 3
    assert [point["created_products"] for point in result["points"]] == [2, 1]
    assert result["points"][0]["active_products"] == 1
    assert result["points"][0]["inactive_products"] == 1

@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/analytics/sales/metrics",
        "/api/v1/analytics/sales/trend",
        "/api/v1/analytics/inventory/risk-distribution",
        "/api/v1/analytics/sales/top-products",
        "/api/v1/analytics/catalog/product-creation-trend",
    ],
)
def test_new_analytics_endpoints_require_authentication(client, path):
    assert client.get(path).status_code == 401

def test_sales_metrics_endpoint_forwards_filters(admin_client, monkeypatch):
    captured = {}

    def fake_metrics(_user, _db, **filters):
        captured.update(filters)
        return {
            "period": "custom",
            "customer_type": "registered",
            "client_id": filters["client_id"],
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "sales_count": 2,
            "gross_sales": "100.00",
            "discounts": "5.00",
            "taxes": "10.00",
            "net_sales": "105.00",
            "average_ticket": "52.50",
            "registered_customer_sales": 2,
            "final_consumer_sales": 0,
        }

    monkeypatch.setattr(analytics_service, "get_sales_metrics", fake_metrics)
    client_id = uuid4()
    response = admin_client.get(
        "/api/v1/analytics/sales/metrics",
        params={
            "period": "custom",
            "customer_type": "registered",
            "client_id": str(client_id),
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
        },
    )

    assert response.status_code == 200
    assert captured["client_id"] == client_id
    assert captured["start_date"].isoformat() == "2026-08-01"
    assert response.json()["average_ticket"] == "52.50"

def test_sales_trend_endpoint_returns_points(admin_client, monkeypatch):
    def fake_trend(_user, _db, **filters):
        return {
            "period": filters["period"],
            "window": filters["window"],
            "customer_type": filters["customer_type"],
            "client_id": None,
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "points": [
                {
                    "period_start": "2026-08-01",
                    "period_label": "2026-08",
                    "sales_count": 3,
                    "gross_sales": "150.00",
                    "discounts": "5.00",
                    "taxes": "10.00",
                    "net_sales": "155.00",
                    "average_ticket": "51.67",
                }
            ],
        }

    monkeypatch.setattr(analytics_service, "get_sales_trend", fake_trend)
    response = admin_client.get(
        "/api/v1/analytics/sales/trend",
        params={"period": "30d", "window": "month"},
    )

    assert response.status_code == 200
    assert response.json()["points"][0]["sales_count"] == 3
    assert response.json()["points"][0]["net_sales"] == "155.00"

def test_risk_distribution_endpoint_returns_all_levels(admin_client, monkeypatch):
    def fake_distribution(_user, _db, **filters):
        return {
            "period": filters["period"],
            "supplier_id": filters["supplier_id"],
            "start_date": "2026-08-01",
            "end_date": "2026-08-31",
            "total_products": 2,
            "distribution": [
                {"level": "critical", "product_count": 1, "percentage": "50.00"},
                {"level": "high", "product_count": 0, "percentage": "0.00"},
                {"level": "medium", "product_count": 0, "percentage": "0.00"},
                {"level": "low", "product_count": 0, "percentage": "0.00"},
                {"level": "healthy", "product_count": 1, "percentage": "50.00"},
            ],
        }

    monkeypatch.setattr(analytics_service, "get_inventory_risk_distribution", fake_distribution)
    response = admin_client.get("/api/v1/analytics/inventory/risk-distribution")

    assert response.status_code == 200
    assert response.json()["total_products"] == 2
    assert [item["level"] for item in response.json()["distribution"]] == [
        "critical",
        "high",
        "medium",
        "low",
        "healthy",
    ]

def test_new_product_analytics_endpoints_forward_filters(admin_client, monkeypatch):
    captured = {}

    def fake_top(_user, _db, **filters):
        captured["top"] = filters
        return {
            "period": "30d", "customer_type": "all", "client_id": None,
            "supplier_id": filters["supplier_id"], "product_id": None,
            "start_date": "2026-08-01", "end_date": "2026-08-31", "products": [],
        }

    def fake_creation(_user, _db, **filters):
        captured["creation"] = filters
        return {
            "period": "30d", "window": "month", "supplier_id": None,
            "active_only": True, "start_date": "2026-08-01", "end_date": "2026-08-31",
            "total_created": 0, "points": [],
        }

    monkeypatch.setattr(analytics_service, "get_top_selling_products", fake_top)
    monkeypatch.setattr(analytics_service, "get_product_creation_trend", fake_creation)
    supplier_id = uuid4()
    top_response = admin_client.get(
        "/api/v1/analytics/sales/top-products",
        params={"supplier_id": str(supplier_id), "limit": 5},
    )
    creation_response = admin_client.get(
        "/api/v1/analytics/catalog/product-creation-trend",
        params={"window": "month", "active_only": True},
    )

    assert top_response.status_code == 200
    assert captured["top"]["supplier_id"] == supplier_id
    assert captured["top"]["limit"] == 5
    assert creation_response.status_code == 200
    assert captured["creation"]["window"] == "month"
    assert captured["creation"]["active_only"] is True

def test_sales_trend_and_risk_distribution_are_in_openapi():
    paths = app.openapi()["paths"]

    assert "/api/v1/analytics/sales/metrics" in paths
    assert "/api/v1/analytics/sales/trend" in paths
    assert "/api/v1/analytics/inventory/risk-distribution" in paths
    assert "/api/v1/analytics/sales/top-products" in paths
    assert "/api/v1/analytics/catalog/product-creation-trend" in paths

@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/v1/analytics/sales/metrics", {"customer_type": "unknown"}),
        ("/api/v1/analytics/sales/trend", {"window": "year"}),
        ("/api/v1/analytics/inventory/risk-distribution", {"period": "invalid"}),
        ("/api/v1/analytics/sales/top-products", {"limit": 0}),
        ("/api/v1/analytics/catalog/product-creation-trend", {"window": "year"}),
    ],
)
def test_new_analytics_endpoints_validate_filters(admin_client, path, params):
    response = admin_client.get(path, params=params)

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"

def test_custom_period_requires_both_dates(admin_client):
    response = admin_client.get(
        "/api/v1/analytics/sales/metrics",
        params={"period": "custom", "start_date": "2026-08-01"},
    )

    assert response.status_code == 400