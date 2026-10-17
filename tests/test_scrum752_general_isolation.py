from types import SimpleNamespace
from uuid import uuid4
import pytest
from sqlalchemy import Boolean, Column, DateTime, MetaData, String, Table, Uuid, create_engine, insert, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import app.services.commercial as commercial_service
from app.schemas.commercial import ClientUpdate
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