"""Real tenant tables on SQLite, for tests that depend on the declared constraints.

The tables come from the same registry production uses, so unique indexes and check
constraints refuse what Postgres would refuse. A partial index declared only with
postgresql_where applies to every row here.
"""
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine, event, insert
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.tenancy.runtime import get_tenant_tables

SCHEMA = "tenant_" + "e" * 32
NOW = datetime(2026, 10, 1, 12, 0, 0)


def tenant_engine(schema_name: str = SCHEMA):
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def attach_schemas(connection, _record):
        connection.execute("ATTACH DATABASE ':memory:' AS global")
        connection.execute(f"ATTACH DATABASE ':memory:' AS {schema_name}")
        # Server defaults call Postgres now().
        connection.create_function("now", 0, lambda: NOW.isoformat(" "))

    tables = get_tenant_tables(schema_name)
    next(iter(tables.values())).metadata.create_all(engine, tables=list(tables.values()))
    return engine, tables


def tenant_user(schema_name: str = SCHEMA, role: str = "manager"):
    return SimpleNamespace(
        id=uuid4(),
        company_id=uuid4(),
        company=SimpleNamespace(is_active=True, schema_name=schema_name),
        role=SimpleNamespace(name=role),
    )


def new_session(engine) -> Session:
    return Session(engine, expire_on_commit=False)


def insert_product(engine, tables, *, stock="10", minimum="2", price="5", active=True):
    product_id = uuid4()
    with new_session(engine) as db:
        db.execute(insert(tables["producto"]).values(
            id=product_id, sku=f"sku-{product_id.hex[:8]}", nombre="Producto", precio_venta=Decimal(price),
            stock_actual=Decimal(stock), stock_minimo=Decimal(minimum), is_active=active,
            created_at=NOW, updated_at=NOW,
        ))
        db.commit()
    return product_id
