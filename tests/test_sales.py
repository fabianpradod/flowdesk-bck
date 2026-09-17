from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

import app.services.commercial as commercial_service
from app.models.tenant.commercial import Venta
from app.models.tenant.registry import build_tenant_metadata
from app.schemas.commercial import SaleCreate, SaleItemCreate
from app.utils.exceptions import AppError
from main import app


SCHEMA_NAME = "tenant_" + "a" * 32


class FakeResult:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


class FakeDB:
    def __init__(self, results):
        self.results = list(results)
        self.statements = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, statement):
        self.statements.append(statement)
        return FakeResult(self.results.pop(0) if self.results else [])

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def make_user():
    return SimpleNamespace(
        id=uuid4(),
        company_id=uuid4(),
        company=SimpleNamespace(is_active=True, schema_name=SCHEMA_NAME),
    )


def make_product(product_id=None, *, stock="10", price="12.50", active=True):
    return {
        "id": product_id or uuid4(),
        "nombre": "Product",
        "precio_venta": Decimal(price),
        "stock_actual": Decimal(stock),
        "stock_minimo": Decimal("2"),
        "is_active": active,
    }


def test_sale_client_is_optional_in_model_and_tenant_metadata():
    assert Venta.__table__.c.cliente_id.nullable is True
    metadata = build_tenant_metadata(SCHEMA_NAME)
    sales = metadata.tables[f"{SCHEMA_NAME}.venta"]
    foreign_key = next(iter(sales.c.cliente_id.foreign_keys))
    assert foreign_key.target_fullname == f"{SCHEMA_NAME}.cliente.id"


def test_sale_schema_rejects_duplicate_product_lines():
    product_id = uuid4()
    with pytest.raises(ValidationError, match="Each product may appear only once"):
        SaleCreate(
            items=[
                SaleItemCreate(producto_id=product_id, cantidad=1),
                SaleItemCreate(producto_id=product_id, cantidad=2),
            ]
        )


def test_create_final_consumer_sale_is_atomic(monkeypatch):
    product = make_product()
    db = FakeDB([[product]])
    user = make_user()
    data = SaleCreate(
        cliente_id=None,
        items=[SaleItemCreate(producto_id=product["id"], cantidad=2)],
        descuento=Decimal("1"),
        impuesto=Decimal("2"),
    )
    monkeypatch.setattr(commercial_service, "_sync_stock_alerts", lambda **_kwargs: None)
    monkeypatch.setattr(
        commercial_service,
        "get_sale",
        lambda sale_id, *_args, **_kwargs: {"id": sale_id, "consumidor_final": True},
    )

    result = commercial_service.create_sale(data, user, db)

    assert result["consumidor_final"] is True
    assert db.commits == 1
    assert db.rollbacks == 0
    compiled = [statement.compile().params for statement in db.statements]
    sale_params = next(params for params in compiled if params.get("estado") == "completada")
    assert sale_params["cliente_id"] is None
    assert sale_params["subtotal"] == Decimal("25.00")
    assert sale_params["total"] == Decimal("26.00")
    movement_params = next(params for params in compiled if params.get("tipo_movimiento") == "salida_venta")
    assert movement_params["stock_anterior"] == Decimal("10")
    assert movement_params["stock_resultante"] == Decimal("8")


def test_create_sale_validates_registered_client(monkeypatch):
    client_id = uuid4()
    product = make_product()
    db = FakeDB(
        [
            [{"id": client_id, "nombre": "Acme", "is_active": True}],
            [product],
        ]
    )
    monkeypatch.setattr(commercial_service, "_sync_stock_alerts", lambda **_kwargs: None)
    monkeypatch.setattr(
        commercial_service,
        "get_sale",
        lambda sale_id, *_args, **kwargs: {
            "id": sale_id,
            "cliente_nombre": kwargs.get("client_name"),
        },
    )

    result = commercial_service.create_sale(
        SaleCreate(cliente_id=client_id, items=[{"producto_id": product["id"], "cantidad": 1}]),
        make_user(),
        db,
    )

    assert result["cliente_nombre"] == "Acme"
    assert db.commits == 1


def test_create_sale_rejects_missing_client_before_writing():
    db = FakeDB([[]])
    with pytest.raises(AppError, match="Client not found"):
        commercial_service.create_sale(
            SaleCreate(cliente_id=uuid4(), items=[{"producto_id": uuid4(), "cantidad": 1}]),
            make_user(),
            db,
        )
    assert db.statements and db.commits == 0


def test_create_sale_rejects_insufficient_stock_before_writing():
    product = make_product(stock="1")
    db = FakeDB([[product]])
    with pytest.raises(AppError, match="Insufficient stock"):
        commercial_service.create_sale(
            SaleCreate(items=[{"producto_id": product["id"], "cantidad": 2}]),
            make_user(),
            db,
        )
    assert len(db.statements) == 1
    assert db.commits == 0


def test_sales_and_purchase_history_routes_are_registered():
    paths = {route.path for route in app.routes}
    assert "/api/v1/commercial/sales" in paths
    assert "/api/v1/commercial/sales/{sale_id}" in paths
    assert "/api/v1/commercial/clients/{client_id}/purchases" in paths
