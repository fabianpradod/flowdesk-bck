from datetime import date, datetime
from types import SimpleNamespace
from uuid import uuid4
from sqlalchemy import Column, Date, DateTime, MetaData, String, Table, Uuid, create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import app.services.reports as reports_service
from app.schemas.reports import ReportDataset

def test_report_audit_is_persisted_with_actor_and_isolated_by_tenant(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    metadata = MetaData()

    def report_table(schema):
        return Table(
            "reporte", metadata,
            Column("id", Uuid(as_uuid=True), primary_key=True),
            Column("tipo", String(50), nullable=False),
            Column("periodo_inicio", Date),
            Column("periodo_fin", Date),
            Column("formato", String(20), nullable=False),
            Column("estado", String(20), nullable=False),
            Column("generado_por_usuario_id", Uuid(as_uuid=True)),
            Column("fecha_generacion", DateTime, nullable=False),
            Column("ruta_archivo", String(255)),
            schema=schema,
        )

    tables = {schema: report_table(schema) for schema in ("tenant_a", "tenant_b")}
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
    monkeypatch.setattr(
        reports_service,
        "_get_tenant_tables_for_user",
        lambda user: {"reporte": tables[user.company.schema_name]},
    )

    dataset = ReportDataset(
        title="Reporte de inventario",
        columns=["SKU"],
        rows=[["SKU-001"]],
        metadata={"periodo_inicio": date(2026, 8, 1), "periodo_fin": date(2026, 8, 31)},
    )
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    original = session_factory()
    reports_service.generate_report(dataset, users["tenant_a"], original, report_type="inventario", report_format="csv")
    reports_service.generate_report(dataset, users["tenant_b"], original, report_type="alertas", report_format="pdf")
    original.close()

    recovered = session_factory()
    history_a = reports_service.list_report_history(users["tenant_a"], recovered)
    history_b = reports_service.list_report_history(users["tenant_b"], recovered)

    assert len(history_a) == 1
    assert history_a[0]["tipo"] == "inventario"
    assert history_a[0]["formato"] == "csv"
    assert history_a[0]["estado"] == "generado"
    assert history_a[0]["generado_por_usuario_id"] == users["tenant_a"].id
    assert history_a[0]["periodo_inicio"] == date(2026, 8, 1)
    assert history_a[0]["periodo_fin"] == date(2026, 8, 31)
    assert isinstance(history_a[0]["fecha_generacion"], datetime)
    assert history_a[0]["ruta_archivo"] is None

    assert len(history_b) == 1
    assert history_b[0]["tipo"] == "alertas"
    assert history_b[0]["formato"] == "pdf"
    assert history_b[0]["generado_por_usuario_id"] == users["tenant_b"].id
    assert history_a[0]["id"] != history_b[0]["id"]

    assert len(recovered.execute(select(tables["tenant_a"])).fetchall()) == 1
    assert len(recovered.execute(select(tables["tenant_b"])).fetchall()) == 1
    recovered.close()
    engine.dispose()