import unittest
from types import SimpleNamespace
from uuid import uuid4

from app.schemas.inventory import SupplierUpdate
from app.services.inventory import (
    create_supplier,
    delete_supplier,
    get_supplier,
    list_suppliers,
    update_supplier,
    update_supplier_status,
)
from app.utils.exceptions import AppError


SCHEMA_NAME = "tenant_" + "a" * 32


class FakeResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def one(self):
        return self.rows[0]

    def __iter__(self):
        return iter(self.rows)


class FakeDB:
    """Returns the queued row batches in order, one per execute() call."""

    def __init__(self, results=None):
        self.results = list(results or [])
        self.statements = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, statement):
        self.statements.append(statement)
        rows = self.results.pop(0) if self.results else []
        return FakeResult(rows)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def make_user():
    company = SimpleNamespace(is_active=True, schema_name=SCHEMA_NAME)
    return SimpleNamespace(company_id=uuid4(), company=company)


def make_supplier(is_active=True, nombre="Acme"):
    return {"id": uuid4(), "nombre": nombre, "is_active": is_active}


def written_columns(statement):
    return {getattr(key, "name", key) for key in statement._values}


class SupplierCreateTests(unittest.TestCase):
    def test_rejects_name_already_used_by_an_active_supplier(self):
        db = FakeDB([[{"id": uuid4()}]])
        data = SimpleNamespace(nombre="Acme", telefono=None, correo=None, direccion=None)

        with self.assertRaises(AppError) as error:
            create_supplier(data, make_user(), db)

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(error.exception.detail, "Supplier name already exists")
        self.assertEqual(db.commits, 0)

    def test_persists_and_returns_the_row_when_the_name_is_free(self):
        created = make_supplier()
        db = FakeDB([[], [], [created]])
        data = SimpleNamespace(nombre="  Acme  ", telefono="5555-0101", correo=None, direccion=None)

        result = create_supplier(data, make_user(), db)

        self.assertEqual(result, created)
        self.assertEqual(db.commits, 1)
        self.assertEqual(db.statements[1].compile().params["nombre"], "Acme")


class SupplierReadTests(unittest.TestCase):
    def test_get_raises_404_when_the_supplier_does_not_exist(self):
        db = FakeDB([[]])

        with self.assertRaises(AppError) as error:
            get_supplier(make_user(), db, uuid4())

        self.assertEqual(error.exception.status_code, 404)
        self.assertEqual(error.exception.detail, "Supplier not found")

    def test_list_applies_search_and_status_filters(self):
        db = FakeDB([[make_supplier()]])

        list_suppliers(make_user(), db, search="  ac  ", is_active=True)

        self.assertIn("%ac%", db.statements[0].compile().params.values())
        self.assertIn("is_active", str(db.statements[0].whereclause))

    def test_list_without_filters_sends_no_bound_parameters(self):
        db = FakeDB([[make_supplier()]])

        list_suppliers(make_user(), db)

        self.assertEqual(db.statements[0].compile().params, {})


class SupplierUpdateTests(unittest.TestCase):
    def test_rejects_a_payload_with_no_fields_set(self):
        db = FakeDB([[make_supplier()]])

        with self.assertRaises(AppError) as error:
            update_supplier(SupplierUpdate(), make_user(), db, uuid4())

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(error.exception.detail, "No fields to update")
        self.assertEqual(db.commits, 0)

    def test_rejects_a_name_held_by_another_active_supplier(self):
        db = FakeDB([[make_supplier()], [{"id": uuid4()}]])

        with self.assertRaises(AppError) as error:
            update_supplier(SupplierUpdate(nombre="Otro"), make_user(), db, uuid4())

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(error.exception.detail, "Supplier name already exists")
        self.assertEqual(db.commits, 0)

    def test_writes_only_the_fields_that_were_sent(self):
        supplier = make_supplier()
        db = FakeDB([[supplier], [], [supplier]])

        update_supplier(SupplierUpdate(telefono="5555-0102"), make_user(), db, supplier["id"])

        self.assertEqual(written_columns(db.statements[1]), {"telefono", "updated_at"})
        self.assertEqual(db.commits, 1)

    def test_keeps_the_current_name_available_to_the_same_supplier(self):
        supplier = make_supplier()
        db = FakeDB([[supplier], [], [], [supplier]])

        update_supplier(SupplierUpdate(nombre="Acme"), make_user(), db, supplier["id"])

        self.assertEqual(db.commits, 1)


class SupplierStatusTests(unittest.TestCase):
    def test_rejects_setting_the_status_it_already_has(self):
        db = FakeDB([[make_supplier(is_active=True)]])

        with self.assertRaises(AppError) as error:
            update_supplier_status(make_user(), db, uuid4(), True)

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(error.exception.detail, "Supplier already has this status")
        self.assertEqual(db.commits, 0)

    def test_refuses_to_deactivate_while_active_products_reference_it(self):
        db = FakeDB([[make_supplier(is_active=True)], [{"id": uuid4()}]])

        with self.assertRaises(AppError) as error:
            update_supplier_status(make_user(), db, uuid4(), False)

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(error.exception.detail, "Supplier still has active products")
        self.assertEqual(db.commits, 0)

    def test_deactivates_when_no_active_product_references_it(self):
        supplier_id = uuid4()
        db = FakeDB([[make_supplier(is_active=True)], [], [], [make_supplier(is_active=False)]])

        result = update_supplier_status(make_user(), db, supplier_id, False)

        self.assertFalse(result["is_active"])
        self.assertEqual(db.commits, 1)
        self.assertEqual(written_columns(db.statements[2]), {"is_active", "updated_at"})

    def test_reactivating_skips_the_active_products_check(self):
        db = FakeDB([[make_supplier(is_active=False)], [], [make_supplier(is_active=True)]])

        result = update_supplier_status(make_user(), db, uuid4(), True)

        self.assertTrue(result["is_active"])
        self.assertEqual(db.commits, 1)


class SupplierDeleteTests(unittest.TestCase):
    def test_does_nothing_when_the_supplier_is_already_inactive(self):
        db = FakeDB([[make_supplier(is_active=False)]])

        self.assertIsNone(delete_supplier(make_user(), db, uuid4()))
        self.assertEqual(db.commits, 0)

    def test_refuses_to_delete_while_active_products_reference_it(self):
        db = FakeDB([[make_supplier(is_active=True)], [{"id": uuid4()}]])

        with self.assertRaises(AppError) as error:
            delete_supplier(make_user(), db, uuid4())

        self.assertEqual(error.exception.status_code, 400)
        self.assertEqual(error.exception.detail, "Supplier still has active products")
        self.assertEqual(db.commits, 0)

    def test_soft_deletes_by_clearing_is_active(self):
        db = FakeDB([[make_supplier(is_active=True)], [], []])

        delete_supplier(make_user(), db, uuid4())

        self.assertEqual(db.commits, 1)
        self.assertIs(db.statements[2].compile().params["is_active"], False)


class SupplierTenancyTests(unittest.TestCase):
    def test_rejects_a_user_without_a_company(self):
        user = SimpleNamespace(company_id=None, company=None)

        with self.assertRaises(AppError) as error:
            list_suppliers(user, FakeDB())

        self.assertEqual(error.exception.status_code, 403)

    def test_rejects_a_user_whose_company_is_inactive(self):
        user = SimpleNamespace(
            company_id=uuid4(),
            company=SimpleNamespace(is_active=False, schema_name=SCHEMA_NAME),
        )

        with self.assertRaises(AppError) as error:
            list_suppliers(user, FakeDB())

        self.assertEqual(error.exception.status_code, 403)

    def test_queries_are_scoped_to_the_company_schema(self):
        db = FakeDB([[make_supplier()]])

        list_suppliers(make_user(), db)

        self.assertIn(SCHEMA_NAME, str(db.statements[0]))


if __name__ == "__main__":
    unittest.main()
