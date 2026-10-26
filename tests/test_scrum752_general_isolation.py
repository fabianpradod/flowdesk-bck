from app.models.tenant.audit import AuditEvent
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4
import pytest
from sqlalchemy import Boolean, Column, DateTime, MetaData, Numeric, String, Table, Uuid, create_engine, insert, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import app.services.commercial as commercial_service
import app.services.inventory as inventory_service
from app.schemas.commercial import ClientUpdate
from app.schemas.inventory import InventoryMovementCreate
from app.utils.exceptions import AppError

def test_real_client_records_are_isolated_between_tenants_and_cross_update_is_not_persisted(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    metadata = MetaData()

    def client_table(schema):
        return Table(
            "cliente", metadata,
            Column("id", Uuid(as_uuid=True), primary_key=True),
            Column("nombre", String(100), nullable=False),
            Column("telefono", String(20)),
            Column("correo", String(150)),
            Column("direccion", String(200)),
            Column("is_active", Boolean, nullable=False),
            Column("created_at", DateTime),
            Column("updated_at", DateTime),
            schema=schema,
        )

    tables = {schema: client_table(schema) for schema in ("tenant_a", "tenant_b")}
    with engine.begin() as connection:
        connection.exec_driver_sql('ATTACH DATABASE ":memory:" AS tenant_a')
        connection.exec_driver_sql('ATTACH DATABASE ":memory:" AS tenant_b')
    for schema in ('tenant_a', 'tenant_b'):
        AuditEvent.__table__.to_metadata(metadata, schema=schema)
    metadata.create_all(engine)

    users = {
        schema: SimpleNamespace(
            id=uuid4(), company_id=uuid4(),
            company=SimpleNamespace(is_active=True, schema_name=schema),
        )
        for schema in tables
    }
    client_ids = {schema: uuid4() for schema in tables}
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = session_factory()
    for schema, name in (("tenant_a", "Cliente A"), ("tenant_b", "Cliente B")):
        db.execute(insert(tables[schema]).values(
            id=client_ids[schema], nombre=name, telefono="5555", correo=f"{schema}@example.com",
            direccion="Dirección original", is_active=True,
        ))
    db.commit()
    db.close()

    monkeypatch.setattr(commercial_service, "get_tenant_tables", lambda schema: {"cliente": tables[schema]})

    session = session_factory()
    assert commercial_service.get_client(client_ids["tenant_a"], users["tenant_a"], session)["nombre"] == "Cliente A"
    assert commercial_service.list_clients(users["tenant_a"], session)[0]["nombre"] == "Cliente A"
    with pytest.raises(AppError) as error:
        commercial_service.get_client(client_ids["tenant_b"], users["tenant_a"], session)
    assert error.value.status_code == 404

    with pytest.raises(AppError) as error:
        commercial_service.update_client(
            client_ids["tenant_b"], ClientUpdate(nombre="No autorizado"), users["tenant_a"], session,
        )
    assert error.value.status_code == 404
    session.close()

    recovered = session_factory()
    row_b = recovered.execute(
        select(tables["tenant_b"]).where(tables["tenant_b"].c.id == client_ids["tenant_b"])
    ).mappings().one()
    assert row_b["nombre"] == "Cliente B"
    assert row_b["direccion"] == "Dirección original"
    assert [row["nombre"] for row in recovered.execute(select(tables["tenant_b"])).mappings()] == ["Cliente B"]
    recovered.close()
    engine.dispose()

def test_inventory_resources_are_isolated_between_tenants_for_reads_and_writes(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    metadata = MetaData()

    def tenant_tables(schema):
        product = Table(
            "producto", metadata,
            Column("id", Uuid(as_uuid=True), primary_key=True),
            Column("nombre", String(100), nullable=False),
            Column("stock_actual", Numeric(18, 2), nullable=False),
            Column("stock_minimo", Numeric(18, 2), nullable=False),
            Column("is_active", Boolean, nullable=False),
            Column("updated_at", DateTime),
            schema=schema,
        )
        movement = Table(
            "movimiento_inventario", metadata,
            Column("id", Uuid(as_uuid=True), primary_key=True),
            Column("producto_id", Uuid(as_uuid=True), nullable=False),
            Column("usuario_id", Uuid(as_uuid=True), nullable=False),
            Column("tipo_movimiento", String(100), nullable=False),
            Column("fecha", DateTime, nullable=False),
            Column("cantidad", Numeric(18, 2), nullable=False),
            Column("stock_anterior", Numeric(18, 2), nullable=False),
            Column("stock_resultante", Numeric(18, 2), nullable=False),
            Column("motivo", String(200)),
            Column("referencia_tipo", String(30)),
            Column("referencia_id", Uuid(as_uuid=True)),
            schema=schema,
        )
        alert = Table(
            "alerta", metadata,
            Column("id", Uuid(as_uuid=True), primary_key=True),
            Column("producto_id", Uuid(as_uuid=True), nullable=False),
            Column("tipo", String(50), nullable=False),
            Column("mensaje", String(500)),
            Column("fecha", DateTime),
            Column("estado", String(50)),
            Column("resuelta_en", DateTime),
            schema=schema,
        )
        return {"producto": product, "movimiento_inventario": movement, "alerta": alert}

    schemas = {schema: tenant_tables(schema) for schema in ("tenant_a", "tenant_b")}
    with engine.begin() as connection:
        connection.exec_driver_sql('ATTACH DATABASE ":memory:" AS tenant_a')
        connection.exec_driver_sql('ATTACH DATABASE ":memory:" AS tenant_b')
    for schema in ('tenant_a', 'tenant_b'):
        AuditEvent.__table__.to_metadata(metadata, schema=schema)
    metadata.create_all(engine)

    users = {
        schema: SimpleNamespace(
            id=uuid4(), company_id=uuid4(),
            company=SimpleNamespace(is_active=True, schema_name=schema),
        )
        for schema in schemas
    }
    product_a = uuid4()
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    db = session_factory()
    db.execute(insert(schemas["tenant_a"]["producto"]).values(
        id=product_a,
        nombre="Producto A",
        stock_actual=Decimal("10.00"),
        stock_minimo=Decimal("2.00"),
        is_active=True,
    ))
    db.commit()

    monkeypatch.setattr(
        inventory_service,
        "_get_tenant_tables_for_user",
        lambda user: schemas[user.company.schema_name],
    )
    monkeypatch.setattr(inventory_service, "_sync_stock_alerts", lambda **_kwargs: None)

    own_movement = inventory_service.create_inventory_movement(
        InventoryMovementCreate(
            producto_id=product_a,
            tipo_movimiento="ajuste_positivo",
            cantidad=Decimal("1.00"),
            motivo="Ajuste propio",
        ),
        users["tenant_a"],
        db,
    )
    assert own_movement["stock_resultante"] == Decimal("11.00")
    db.close()

    other_tenant = session_factory()
    try:
        assert inventory_service.list_inventory_movements(users["tenant_b"], other_tenant) == []

        with pytest.raises(AppError) as error:
            inventory_service.create_inventory_movement(
                InventoryMovementCreate(
                    producto_id=product_a,
                    tipo_movimiento="ajuste_negativo",
                    cantidad=Decimal("3.00"),
                    motivo="Intento cruzado",
                ),
                users["tenant_b"],
                other_tenant,
            )
        assert error.value.status_code == 404
        assert "Producto A" not in str(error.value.detail)
    finally:
        other_tenant.close()

    recovered = session_factory()
    try:
        product = recovered.execute(
            select(schemas["tenant_a"]["producto"]).where(
                schemas["tenant_a"]["producto"].c.id == product_a
            )
        ).mappings().one()
        movements = recovered.execute(
            select(schemas["tenant_a"]["movimiento_inventario"]).where(
                schemas["tenant_a"]["movimiento_inventario"].c.producto_id == product_a
            )
        ).mappings().all()
        assert product["stock_actual"] == Decimal("11.00")
        assert len(movements) == 1
        assert movements[0]["usuario_id"] == users["tenant_a"].id
    finally:
        recovered.close()
        engine.dispose()