import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, MetaData, String, Table


CLIENT_ID = uuid4()


class CommercialClientTests(unittest.TestCase):
    def test_create_client_inserts_clean_payload(self):
        from app.schemas.commercial import ClientCreate
        from app.services.commercial import create_client

        tenant_tables = build_tenant_tables()
        created_at = datetime.now(timezone.utc)
        db = FakeDB(
            [
                FakeResult([]),
                FakeResult([]),
                FakeResult(
                    [
                        {
                            "id": CLIENT_ID,
                            "nombre": "Acme",
                            "telefono": "5555-0000",
                            "correo": "sales@acme.com",
                            "direccion": "Zona 10",
                            "is_active": True,
                            "created_at": created_at,
                            "updated_at": created_at,
                        }
                    ]
                ),
            ]
        )
        data = ClientCreate(
            nombre="  Acme  ",
            telefono="5555-0000",
            correo=" SALES@ACME.COM ",
            direccion=" Zona 10 ",
        )

        with patch("app.services.commercial.get_tenant_tables", return_value=tenant_tables):
            client = create_client(data, tenant_user(), db)

        self.assertEqual(client["nombre"], "Acme")
        self.assertEqual(db.commits, 1)
        self.assertEqual(db.rollbacks, 0)
        self.assertEqual(len(db.executed), 3)
        insert_sql = str(db.executed[1]).lower()
        self.assertIn("insert into", insert_sql)
        self.assertIn("cliente", insert_sql)

    def test_create_client_rejects_duplicate_email(self):
        from app.schemas.commercial import ClientCreate
        from app.services.commercial import create_client
        from app.utils.exceptions import AppError

        tenant_tables = build_tenant_tables()
        db = FakeDB([FakeResult([{"id": uuid4()}])])
        data = ClientCreate(nombre="Acme", correo="sales@acme.com")

        with patch("app.services.commercial.get_tenant_tables", return_value=tenant_tables):
            with self.assertRaises(AppError) as error:
                create_client(data, tenant_user(), db)

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(error.exception.detail, "Client email already exists")
        self.assertEqual(db.commits, 0)

    def test_update_client_requires_existing_client(self):
        from app.schemas.commercial import ClientUpdate
        from app.services.commercial import update_client
        from app.utils.exceptions import AppError

        tenant_tables = build_tenant_tables()
        db = FakeDB([FakeResult([])])

        with patch("app.services.commercial.get_tenant_tables", return_value=tenant_tables):
            with self.assertRaises(AppError) as error:
                update_client(CLIENT_ID, ClientUpdate(nombre="Nuevo"), tenant_user(), db)

        self.assertEqual(error.exception.status_code, 404)
        self.assertEqual(error.exception.detail, "Client not found")

    def test_list_clients_supports_search_and_active_filter(self):
        from app.services.commercial import list_clients

        tenant_tables = build_tenant_tables()
        db = FakeDB(
            [
                FakeResult(
                    [
                        {
                            "id": CLIENT_ID,
                            "nombre": "Acme",
                            "telefono": None,
                            "correo": None,
                            "direccion": None,
                            "is_active": True,
                            "created_at": datetime.now(timezone.utc),
                            "updated_at": datetime.now(timezone.utc),
                        }
                    ]
                )
            ]
        )

        with patch("app.services.commercial.get_tenant_tables", return_value=tenant_tables):
            clients = list_clients(tenant_user(), db, search="acme", active_only=True)

        self.assertEqual(clients[0]["nombre"], "Acme")
        rendered_query = str(db.executed[0]).lower()
        self.assertIn("is_active", rendered_query)
        self.assertIn("lower", rendered_query)

    def test_update_status_soft_deletes_client(self):
        from app.services.commercial import delete_client

        tenant_tables = build_tenant_tables()
        db = FakeDB([FakeResult([{"id": CLIENT_ID}])])

        with patch("app.services.commercial.get_tenant_tables", return_value=tenant_tables):
            delete_client(CLIENT_ID, tenant_user(), db)

        self.assertEqual(db.commits, 1)
        update_sql = str(db.executed[1]).lower()
        self.assertIn("update", update_sql)
        self.assertIn("cliente", update_sql)


def tenant_user():
    return SimpleNamespace(company_id=uuid4(), company=SimpleNamespace(is_active=True, schema_name="tenant_test"))


def build_tenant_tables():
    metadata = MetaData()
    Table(
        "cliente",
        metadata,
        Column("id", String, primary_key=True),
        Column("nombre", String(100), nullable=False),
        Column("telefono", String(20), nullable=True),
        Column("correo", String(150), nullable=True),
        Column("direccion", String(200), nullable=True),
        Column("is_active", Boolean, nullable=False),
        Column("created_at", DateTime, nullable=False),
        Column("updated_at", DateTime, nullable=False),
        schema="tenant_test",
    )
    return {
        table.name: table
        for table in metadata.tables.values()
        if isinstance(table, Table) and table.schema == "tenant_test"
    }


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def one(self):
        if not self.rows:
            raise AssertionError("Expected one row")
        return self.rows[0]

    def __iter__(self):
        return iter(self.rows)


class FakeDB:
    def __init__(self, results):
        self.results = list(results)
        self.executed = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, statement, *_args, **_kwargs):
        self.executed.append(statement)
        if not self.results:
            return FakeResult([])
        return self.results.pop(0)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


if __name__ == "__main__":
    unittest.main()
