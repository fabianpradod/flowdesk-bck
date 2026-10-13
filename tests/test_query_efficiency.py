"""Query count and per-row work of the endpoints the load test found expensive.

Each case runs against an in-memory SQLite engine and counts the SELECT statements
that reach it, so the numbers are the round trips the code really makes.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import Column, MetaData, Table, Uuid, create_engine, event, insert
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.dependencies.auth import get_current_user
from app.core.database import Base
from app.core.security import create_access_token
from app.models.companies import Company
from app.models.roles import Role
from app.models.users import User
from app.schemas.commercial import ClientCreate, ClientResponse
from app.services import commercial as commercial_service
from app.services import inventory as inventory_service
from app.tenancy.runtime import get_tenant_tables


def sqlite_engine():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def attach_global(connection, _record):
        connection.execute("ATTACH DATABASE ':memory:' AS global")

    return engine


def count_selects(engine):
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def record(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    return statements


# --- authentication -----------------------------------------------------------


@pytest.fixture
def auth_db():
    engine = sqlite_engine()
    Base.metadata.create_all(engine, tables=[Role.__table__, Company.__table__, User.__table__])
    with Session(engine) as db:
        role = Role(name="manager", description="", created_at=datetime(2026, 1, 1))
        company = Company(name="Acme", schema_name="tenant_" + "a" * 32, is_active=True, created_at=datetime(2026, 1, 1))
        db.add_all([role, company])
        db.flush()
        user = User(
            username="manager",
            email="manager@example.com",
            password="x",
            role_id=role.id,
            company_id=company.id,
            is_active=True,
            created_at=datetime(2026, 1, 1),
        )
        db.add(user)
        db.commit()
        user_id = user.id
    with Session(engine) as db:
        yield engine, db, user_id


def test_current_user_loads_company_and_role_in_one_query(auth_db):
    engine, db, user_id = auth_db
    token = create_access_token({"sub": str(user_id)})
    selects = count_selects(engine)

    user = get_current_user(token=token, db=db)

    assert (user.company.schema_name, user.role.name) == ("tenant_" + "a" * 32, "manager")
    assert len(selects) == 1


# --- client listing -----------------------------------------------------------


def client_row(**overrides):
    row = {
        "id": uuid4(),
        "nombre": "Cliente",
        "telefono": None,
        "correo": "cliente@example.com",
        "direccion": None,
        "is_active": True,
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 1),
    }
    return {**row, **overrides}


def test_client_response_keeps_email_normalization():
    response = ClientResponse.model_validate(client_row(correo="  Mixed.Case@Example.COM "))

    assert response.correo == "mixed.case@example.com"


def test_client_response_does_not_revalidate_stored_emails(monkeypatch):
    import email_validator

    def fail(*_args, **_kwargs):
        raise AssertionError("stored emails were validated again on output")

    monkeypatch.setattr(email_validator, "validate_email", fail)

    assert ClientResponse.model_validate(client_row()).correo == "cliente@example.com"


def test_client_input_still_validates_email():
    with pytest.raises(ValidationError):
        ClientCreate(nombre="Cliente", correo="not-an-email")


# --- inventory analytics ------------------------------------------------------


def movement_rows(count, start=datetime(2026, 1, 1)):
    return [
        {
            "producto_id": UUID(int=index % 3 + 1),
            "tipo_movimiento": "entrada_manual" if index % 2 else "salida_manual",
            "fecha": start + timedelta(days=index % 50),
            "cantidad": Decimal("2"),
            "stock_resultante": Decimal(index),
            "sku": f"SKU-{index % 3}",
            "nombre": f"Producto {index % 3}",
            "stock_actual": Decimal("10"),
            "stock_minimo": Decimal("5"),
        }
        for index in range(count)
    ]


def test_aggregation_builds_each_bucket_once(monkeypatch):
    created = []
    original = inventory_service._empty_bucket

    def counting(bucket_start, window):
        created.append(bucket_start)
        return original(bucket_start, window)

    monkeypatch.setattr(inventory_service, "_empty_bucket", counting)

    points = inventory_service._aggregate_movement_rows(movement_rows(600), window="month", include_previous=True)

    assert len(points) == 2
    assert len(created) == 2


class CaptureDB:
    def __init__(self):
        self.statements = []

    def execute(self, statement, *_args, **_kwargs):
        self.statements.append(str(statement))
        return self

    def mappings(self):
        return []


@pytest.mark.parametrize(
    "service, kwargs, joins_products",
    [
        (inventory_service.get_monthly_behavior, {"period": "6m"}, False),
        (inventory_service.get_inventory_trend, {"period": "30d", "window": "day"}, False),
        (inventory_service.get_product_analytics, {"period": "30d", "sort_by": "outbound", "limit": 10}, True),
    ],
)
def test_movement_analytics_only_read_the_columns_they_use(monkeypatch, service, kwargs, joins_products):
    tables = get_tenant_tables("tenant_" + "b" * 32)
    monkeypatch.setattr(inventory_service, "_get_tenant_tables_for_user", lambda _user: tables)
    db = CaptureDB()

    service(object(), db, **kwargs)

    (statement,) = db.statements
    assert ("JOIN" in statement) == joins_products
    assert ("stock_minimo" in statement) == joins_products


# --- client purchase history --------------------------------------------------


@pytest.fixture
def sales_db(monkeypatch):
    real = get_tenant_tables("tenant_" + "c" * 32)
    metadata = MetaData()
    tables = {
        name: Table(
            name,
            metadata,
            *[
                Column(column.name, Uuid() if isinstance(column.type, Uuid) else column.type, primary_key=column.primary_key)
                for column in real[name].columns
            ],
        )
        for name in ("cliente", "venta", "detalle_venta")
    }
    engine = sqlite_engine()
    metadata.create_all(engine)
    monkeypatch.setattr(commercial_service, "_tenant_tables", lambda _user: tables)

    client_id = uuid4()
    now = datetime(2026, 10, 1)
    with engine.begin() as connection:
        connection.execute(insert(tables["cliente"]), [client_row(id=client_id, nombre="Ana")])
        for day in range(3):
            sale_id = UUID(int=100 + day)
            connection.execute(
                insert(tables["venta"]),
                [{
                    "id": sale_id, "usuario_id": uuid4(), "cliente_id": client_id, "fecha": now + timedelta(days=day),
                    "subtotal": Decimal("10"), "descuento": Decimal("0"), "impuesto": Decimal("1.2"),
                    "tasa_impuesto": Decimal("12"), "es_exenta": False, "total": Decimal("11.2"),
                    "estado": "completada", "created_at": now, "updated_at": now,
                }],
            )
            connection.execute(
                insert(tables["detalle_venta"]),
                [
                    {
                        "id": UUID(int=1000 + 10 * day + line), "venta_id": sale_id, "producto_id": uuid4(),
                        "cantidad": Decimal("1"), "precio_unitario": Decimal("5"), "subtotal": Decimal("5"),
                    }
                    for line in (1, 0)
                ],
            )
    with Session(engine) as db:
        yield engine, db, client_id


def test_purchase_history_keeps_order_and_items(sales_db):
    _engine, db, client_id = sales_db

    sales = commercial_service.list_client_purchases(client_id, object(), db, limit=2)

    assert [sale["id"] for sale in sales] == [UUID(int=102), UUID(int=101)]
    assert [[item["id"] for item in sale["items"]] for sale in sales] == [
        [UUID(int=1020), UUID(int=1021)],
        [UUID(int=1010), UUID(int=1011)],
    ]
    assert all(sale["cliente_nombre"] == "Ana" and sale["consumidor_final"] is False for sale in sales)


def test_purchase_history_query_count_does_not_grow_with_sales(sales_db):
    engine, db, client_id = sales_db
    selects = count_selects(engine)

    commercial_service.list_client_purchases(client_id, object(), db, limit=3)

    assert len(selects) == 3
