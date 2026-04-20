import re
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4


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


class TenantBootstrapTests(unittest.TestCase):
    def test_generate_schema_name_uses_prefixed_uuid_hex(self):
        from app.tenancy.bootstrap import generate_schema_name

        company_id = UUID("12345678-1234-5678-1234-567812345678")

        schema_name = generate_schema_name(company_id)

        self.assertEqual(schema_name, "tenant_12345678123456781234567812345678")
        self.assertRegex(schema_name, r"^tenant_[a-f0-9]{32}$")

    def test_build_tenant_metadata_contains_expected_tables(self):
        from app.tenancy.bootstrap import build_tenant_metadata

        schema_name = "tenant_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        metadata = build_tenant_metadata(schema_name)

        self.assertEqual(
            set(metadata.tables.keys()),
            {
                f"{schema_name}.proveedor",
                f"{schema_name}.producto",
                f"{schema_name}.cliente",
                f"{schema_name}.venta",
                f"{schema_name}.detalle_venta",
                f"{schema_name}.tarea",
                f"{schema_name}.reporte",
                f"{schema_name}.movimiento_inventario",
                f"{schema_name}.alerta",
            },
        )

        movement_table = metadata.tables[f"{schema_name}.movimiento_inventario"]
        fk_targets = {fk.target_fullname for fk in movement_table.foreign_keys}
        self.assertIn(f"{schema_name}.producto.id", fk_targets)
        self.assertIn("global.users.id", fk_targets)

    def test_register_company_derives_schema_and_bootstraps_before_commit(self):
        from app.models.companies import Company
        from app.models.roles import Role
        from app.services.auth import register_company

        db = FakeDB(
            query_results={
                Company: [None],
                Role: [Role(id=7, name="admin", description="Admin role")],
            }
        )
        payload = SimpleNamespace(
            name="Acme",
            admin_email="admin@example.com",
            admin_username="acme-admin",
        )

        with (
            patch("app.services.auth.bootstrap_tenant_schema") as bootstrap_mock,
            patch("app.services.auth.create_access_token", return_value="test-token"),
            patch("app.services.auth._send_password_set_email") as send_email_mock,
        ):
            company = register_company(payload, db)

        self.assertRegex(company.schema_name, r"^tenant_[a-f0-9]{32}$")
        self.assertEqual(db.commits, 1)
        bootstrap_mock.assert_called_once_with(db.connection_obj, company.schema_name)
        send_email_mock.assert_called_once_with("admin@example.com", "test-token")

    def test_register_company_rolls_back_when_bootstrap_fails(self):
        from app.models.companies import Company
        from app.models.roles import Role
        from app.services.auth import register_company

        db = FakeDB(
            query_results={
                Company: [None],
                Role: [Role(id=7, name="admin", description="Admin role")],
            }
        )
        payload = SimpleNamespace(
            name="Acme",
            admin_email="admin@example.com",
            admin_username="acme-admin",
        )

        with (
            patch("app.services.auth.bootstrap_tenant_schema", side_effect=RuntimeError("boom")),
            patch("app.services.auth._send_password_set_email") as send_email_mock,
        ):
            with self.assertRaises(RuntimeError):
                register_company(payload, db)

        self.assertEqual(db.commits, 0)
        self.assertEqual(db.rollbacks, 1)
        send_email_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
