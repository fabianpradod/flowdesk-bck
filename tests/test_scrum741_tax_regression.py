from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
from sqlalchemy import Boolean, Column, DateTime, MetaData, Numeric, String, Table, Text, Uuid, create_engine, insert, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import app.services.commercial as commercial_service
from app.schemas.commercial import SaleCreate

def _tenant_tables(metadata, schema):
    return {
        "producto": Table(
            "producto", metadata,
            Column("id", Uuid(as_uuid=True), primary_key=True),
            Column("nombre", String(100), nullable=False),
            Column("precio_venta", Numeric(10, 2), nullable=False),
            Column("stock_actual", Numeric(12, 2), nullable=False),
            Column("stock_minimo", Numeric(12, 2), nullable=False),
            Column("is_active", Boolean, nullable=False),
            Column("updated_at", DateTime, nullable=False),
            schema=schema,
        ),
        "cliente": Table(
            "cliente", metadata,
            Column("id", Uuid(as_uuid=True), primary_key=True),
            Column("nombre", String(100), nullable=False),
            Column("is_active", Boolean, nullable=False),
            schema=schema,
        ),
        "configuracion_tributaria": Table(
            "configuracion_tributaria", metadata,
            Column("id", Uuid(as_uuid=True), primary_key=True),
            Column("tasa_impuesto", Numeric(5, 2), nullable=False),
            Column("updated_at", DateTime, nullable=False),
            Column("created_at", DateTime, nullable=False),
            schema=schema,
        ),
        "venta": Table(
            "venta", metadata,
            Column("id", Uuid(as_uuid=True), primary_key=True),
            Column("usuario_id", Uuid(as_uuid=True), nullable=False),
            Column("cliente_id", Uuid(as_uuid=True), nullable=True),
            Column("fecha", DateTime, nullable=False),
            Column("subtotal", Numeric(10, 2), nullable=False),
            Column("descuento", Numeric(10, 2), nullable=False),
            Column("impuesto", Numeric(10, 2), nullable=False),
            Column("tasa_impuesto", Numeric(5, 2), nullable=False),
            Column("es_exenta", Boolean, nullable=False),
            Column("total", Numeric(10, 2), nullable=False),
            Column("estado", String(20), nullable=False),
            Column("created_at", DateTime, nullable=False),
            Column("updated_at", DateTime, nullable=False),
            schema=schema,
        ),
        "detalle_venta": Table(
            "detalle_venta", metadata,
            Column("id", Uuid(as_uuid=True), primary_key=True),
            Column("venta_id", Uuid(as_uuid=True), nullable=False),
            Column("producto_id", Uuid(as_uuid=True), nullable=False),
            Column("cantidad", Numeric(12, 2), nullable=False),
            Column("precio_unitario", Numeric(10, 2), nullable=False),
            Column("subtotal", Numeric(10, 2), nullable=False),
            schema=schema,
        ),
        "movimiento_inventario": Table(
            "movimiento_inventario", metadata,
            Column("id", Uuid(as_uuid=True), primary_key=True),
            Column("producto_id", Uuid(as_uuid=True), nullable=False),
            Column("usuario_id", Uuid(as_uuid=True), nullable=False),
            Column("tipo_movimiento", String(30), nullable=False),
            Column("fecha", DateTime, nullable=False),
            Column("cantidad", Numeric(12, 2), nullable=False),
            Column("stock_anterior", Numeric(12, 2), nullable=False),
            Column("stock_resultante", Numeric(12, 2), nullable=False),
            Column("motivo", String(200), nullable=False),
            Column("referencia_tipo", String(30), nullable=False),
            Column("referencia_id", Uuid(as_uuid=True), nullable=False),
            schema=schema,
        ),
        "alerta": Table(
            "alerta", metadata,
            Column("id", Uuid(as_uuid=True), primary_key=True),
            Column("producto_id", Uuid(as_uuid=True), nullable=False),
            schema=schema,
        ),
    }

def test_sales_persist_tax_values_and_use_the_current_tenant_configuration(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    metadata = MetaData()
    tables = {schema: _tenant_tables(metadata, schema) for schema in ("tenant_a", "tenant_b")}
    with engine.begin() as connection:
        connection.exec_driver_sql('ATTACH DATABASE ":memory:" AS tenant_a')
        connection.exec_driver_sql('ATTACH DATABASE ":memory:" AS tenant_b')
    metadata.create_all(engine)

    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = session_factory()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    product_ids = {schema: uuid4() for schema in tables}
    users = {}

    for schema, rate in (("tenant_a", Decimal("12.00")), ("tenant_b", Decimal("15.00"))):
        product = tables[schema]["producto"]
        config = tables[schema]["configuracion_tributaria"]
        db.execute(insert(product).values(
            id=product_ids[schema], nombre="Taxable item", precio_venta=Decimal("100.00"),
            stock_actual=Decimal("10.00"), stock_minimo=Decimal("1.00"), is_active=True, updated_at=now,
        ))
        db.execute(insert(config).values(
            id=uuid4(), tasa_impuesto=rate, created_at=now, updated_at=now,
        ))
        users[schema] = SimpleNamespace(
            id=uuid4(), company_id=uuid4(),
            company=SimpleNamespace(is_active=True, schema_name=schema),
        )
    db.commit()
    db.close()

    monkeypatch.setattr(commercial_service, "get_tenant_tables", lambda schema: tables[schema])
    monkeypatch.setattr(commercial_service, "_sync_stock_alerts", lambda **_kwargs: None)

    sale_ids = {}
    for schema, expected_tax, expected_total in (
        ("tenant_a", Decimal("12.00"), Decimal("112.00")),
        ("tenant_b", Decimal("15.00"), Decimal("115.00")),
    ):
        session = session_factory()
        result = commercial_service.create_sale(
            SaleCreate(items=[{"producto_id": product_ids[schema], "cantidad": 1}]),
            users[schema], session,
        )
        sale_ids[schema] = result["id"]
        assert result["subtotal"] == Decimal("100.00")
        assert result["impuesto"] == expected_tax
        assert result["tasa_impuesto"] == expected_tax
        assert result["total"] == expected_total
        session.close()

    recovered = session_factory()
    for schema, expected_tax, expected_total in (
        ("tenant_a", Decimal("12.00"), Decimal("112.00")),
        ("tenant_b", Decimal("15.00"), Decimal("115.00")),
    ):
        row = recovered.execute(
            select(tables[schema]["venta"]).where(tables[schema]["venta"].c.id == sale_ids[schema])
        ).mappings().one()
        assert row["subtotal"] == Decimal("100.00")
        assert row["descuento"] == Decimal("0.00")
        assert row["impuesto"] == expected_tax
        assert row["tasa_impuesto"] == expected_tax
        assert row["total"] == expected_total
        assert row["estado"] == "completada"

    assert recovered.execute(select(tables["tenant_a"]["venta"])).fetchall()[0][0] == sale_ids["tenant_a"]
    assert recovered.execute(select(tables["tenant_b"]["venta"])).fetchall()[0][0] == sale_ids["tenant_b"]
    recovered.close()
    engine.dispose()