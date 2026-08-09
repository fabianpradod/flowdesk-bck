import pytest
import re
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4
from app.models.tenant.base import Base, TENANT_SCHEMA
from app.models.tenant.commercial import Cliente, DetalleVenta, Venta
from app.models.tenant.inventory import Alerta, MovimientoInventario, Producto, Proveedor, ProveedorProducto
from app.models.tenant.operations import Reporte, Tarea
from app.models.companies import Company
from app.models.roles import Role
from app.services.auth import register_company
from app.tenancy.bootstrap import bootstrap_tenant_schema, generate_schema_name, validate_schema_name
from app.tenancy.runtime import get_user_schema_name, get_tenant_tables
from app.utils.exceptions import AppError
from app.models.tenant.registry import build_tenant_metadata, get_tenant_table_names

class FakeQuery:
    def __init__(self, db, model):
        self.db = db
        self.model = model

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        queue = self.db.query_results.setdefault(self.model, [])
        if queue:
            return queue.pop(0)
        return None

class FakeDB:
    def __init__(self, query_results=None):
        self.query_results = query_results or {}
        self.added = []
        self.connection_obj = object()
        self.commits = 0
        self.rollbacks = 0
        self.refreshed = []

    def query(self, model):
        return FakeQuery(self, model)

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        for obj in self.added:
            if obj.__class__.__name__ == "Company" and getattr(obj, "id", None) is None:
                obj.id = uuid4()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def refresh(self, obj):
        self.refreshed.append(obj)

    def connection(self):
        return self.connection_obj

def test_generate_schema_name_uses_prefixed_uuid_hex():
    company_id = UUID("12345678-1234-5678-1234-567812345678")

    schema_name = generate_schema_name(company_id)

    assert schema_name == "tenant_12345678123456781234567812345678"
    assert re.fullmatch(r"^tenant_[a-f0-9]{32}$", schema_name)

def test_build_tenant_metadata_contains_expected_tables():
    schema_name = "tenant_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    metadata = build_tenant_metadata(schema_name)
    table_names = get_tenant_table_names()

    expected_table_names = {
        "proveedor",
        "producto",
        "proveedor_producto",
        "movimiento_inventario",
        "alerta",
        "cliente",
        "venta",
        "detalle_venta",
        "tarea",
        "reporte",
    }
    tenant_models = {
        Proveedor,
        ProveedorProducto,
        Producto,
        MovimientoInventario,
        Alerta,
        Cliente,
        Venta,
        DetalleVenta,
        Tarea,
        Reporte,
    }

    assert set(table_names) == expected_table_names
    assert len(table_names) == len(expected_table_names)

    for model in tenant_models:
        assert issubclass(model, Base)
        assert model.__tablename__ in expected_table_names
        assert model.__table__.schema == TENANT_SCHEMA

    assert set(metadata.tables.keys()) == (
        {
            f"{schema_name}.{table_name}"
            for table_name in expected_table_names
        }
        | {"global.users"}
    )

    supplier_product_table = metadata.tables[
        f"{schema_name}.proveedor_producto"
    ]

    fk_targets = {
        fk.target_fullname
        for fk in supplier_product_table.foreign_keys
    }

    assert f"{schema_name}.proveedor.id" in fk_targets
    assert f"{schema_name}.producto.id" in fk_targets

    assert (
        table_names.index("proveedor")
        < table_names.index("proveedor_producto")
    )

    assert (
        table_names.index("producto")
        < table_names.index("proveedor_producto")
    )

    movement_table = metadata.tables[f"{schema_name}.movimiento_inventario"]
    fk_targets = {fk.target_fullname for fk in movement_table.foreign_keys}
    assert f"{schema_name}.producto.id" in fk_targets
    assert "global.users.id" in fk_targets

    assert f"{schema_name}.usuario" not in metadata.tables
    assert f"{schema_name}.rol" not in metadata.tables
    assert f"{schema_name}.warehouse" not in metadata.tables
    assert f"{schema_name}.warehouses" not in metadata.tables

    sale_table = metadata.tables[f"{schema_name}.venta"]
    task_table = metadata.tables[f"{schema_name}.tarea"]
    report_table = metadata.tables[f"{schema_name}.reporte"]
    assert "global.users.id" in {fk.target_fullname for fk in sale_table.foreign_keys}
    assert "global.users.id" in {fk.target_fullname for fk in task_table.foreign_keys}
    assert "global.users.id" in {fk.target_fullname for fk in report_table.foreign_keys}

def test_tenant_table_creation_order_preserves_foreign_keys():
    table_names = get_tenant_table_names()

    assert table_names.index("proveedor") < table_names.index("producto")
    assert table_names.index("cliente") < table_names.index("venta")
    assert table_names.index("venta") < table_names.index("detalle_venta")
    assert table_names.index("producto") < table_names.index("detalle_venta")
    assert table_names.index("producto") < table_names.index("movimiento_inventario")
    assert table_names.index("producto") < table_names.index("alerta")

def test_register_company_derives_schema_and_bootstraps_before_commit():
    db = FakeDB(
        query_results = {
            Company: [None],
            Role: [Role(id = 7, name = "admin", description = "Admin role")],
        }
    )
    payload = SimpleNamespace(
        name = "Acme",
        admin_email = "admin@example.com",
        admin_username = "acme-admin",
    )

    with (
        patch("app.services.auth.bootstrap_tenant_schema") as bootstrap_mock,
        patch("app.services.auth.create_access_token", return_value="test-token"),
        patch("app.services.auth.send_password_set_email") as send_email_mock,
    ):
        company = register_company(payload, db)

    assert re.fullmatch(r"^tenant_[a-f0-9]{32}$", company.schema_name)
    assert db.commits == 1
    bootstrap_mock.assert_called_once_with(db.connection_obj, company.schema_name)
    send_email_mock.assert_called_once_with("admin@example.com", "test-token")

def test_register_company_rolls_back_when_bootstrap_fails():
    db = FakeDB(
        query_results = {
            Company: [None],
            Role: [Role(id = 7, name="admin", description="Admin role")],
        }
    )
    payload = SimpleNamespace(
        name = "Acme",
        admin_email = "admin@example.com",
        admin_username = "acme-admin",
    )

    with (
        patch("app.services.auth.bootstrap_tenant_schema", side_effect=RuntimeError("boom")),
        patch("app.services.auth.send_password_set_email") as send_email_mock,
    ):
        with pytest.raises(RuntimeError):
            register_company(payload, db)

    assert db.commits == 0
    assert db.rollbacks == 1
    send_email_mock.assert_not_called()

def test_validate_schema_name_accepts_valid_name():
    validate_schema_name(
        "tenant_1234567890abcdef1234567890abcdef"
    )

def test_validate_schema_name_rejects_invalid_name():
    invalid_names = [
        "tenant",
        "tenant-test",
        "tenant_123",
        "public",
        "global",
        "tenant_ABCDEF",
        "tenant_123456789",
    ]

    for name in invalid_names:
        with pytest.raises(ValueError):
            validate_schema_name(name)

def test_bootstrap_executes_create_schema():
    connection = MagicMock()

    with patch("app.tenancy.bootstrap.build_tenant_metadata") as metadata_mock:
        metadata = MagicMock()
        metadata.tables = {}
        metadata.create_all = MagicMock()

        metadata_mock.return_value = metadata

        with patch("app.tenancy.bootstrap.get_tenant_table_names", return_value = []):
            bootstrap_tenant_schema(
                connection,
                "tenant_1234567890abcdef1234567890abcdef"
            )

    connection.execute.assert_called()

def test_get_user_schema_name():
    company = SimpleNamespace(
        is_active = True,
        schema_name = "tenant_demo"
    )

    user = SimpleNamespace(
        company_id = uuid4(),
        company = company
    )

    schema = get_user_schema_name(user)

    assert schema == "tenant_demo"

def test_get_user_schema_without_company():
    user = SimpleNamespace(
        company_id = None,
        company = None
    )

    with pytest.raises(AppError):
        get_user_schema_name(user)

def test_get_user_schema_company_inactive():
    company = SimpleNamespace(
        is_active = False,
        schema_name = "tenant_demo"
    )

    user = SimpleNamespace(
        company_id = uuid4(),
        company = company
    )

    with pytest.raises(AppError):
        get_user_schema_name(user)

def test_get_user_schema_without_schema():
    company = SimpleNamespace(
        is_active = True,
        schema_name = ""
    )

    user = SimpleNamespace(
        company_id = uuid4(),
        company = company
    )

    with pytest.raises(AppError):
        get_user_schema_name(user)

def test_get_tenant_tables_is_cached():
    schema = "tenant_1234567890abcdef1234567890abcdef"

    get_tenant_tables.cache_clear()

    first = get_tenant_tables(schema)
    second = get_tenant_tables(schema)

    assert first is second