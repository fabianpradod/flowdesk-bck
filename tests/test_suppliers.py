from types import SimpleNamespace
from uuid import uuid4
import pytest
from app.schemas.inventory import SupplierUpdate
from app.services.inventory import create_supplier, delete_supplier, get_supplier, list_suppliers, update_supplier, update_supplier_status
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
    company = SimpleNamespace(
        is_active=True,
        schema_name=SCHEMA_NAME,
    )

    return SimpleNamespace(
        company_id=uuid4(),
        company=company,
    )

def make_supplier(
    is_active=True,
    nombre="Acme",
):
    return {
        "id": uuid4(),
        "nombre": nombre,
        "is_active": is_active,
    }

def written_columns(statement):
    return {
        getattr(key, "name", key)
        for key in statement._values
    }

def test_rejects_name_already_used_by_an_active_supplier():
    db = FakeDB([
        [{"id": uuid4()}],
    ])

    data = SimpleNamespace(
        nombre="Acme",
        telefono=None,
        correo=None,
        direccion=None,
    )

    with pytest.raises(AppError) as error:
        create_supplier(
            data,
            make_user(),
            db,
        )

    assert error.value.status_code == 400
    assert error.value.detail == "Supplier name already exists"
    assert db.commits == 0

def test_persists_and_returns_the_row_when_the_name_is_free():
    created = make_supplier()

    db = FakeDB([
        [],
        [],
        [created],
    ])

    data = SimpleNamespace(
        nombre="  Acme  ",
        telefono="5555-0101",
        correo=None,
        direccion=None,
    )

    result = create_supplier(
        data,
        make_user(),
        db,
    )

    assert result == created
    assert db.commits == 1

    assert (
        db.statements[1]
        .compile()
        .params["nombre"]
        == "Acme"
    )

def test_get_raises_404_when_supplier_does_not_exist():
    db = FakeDB([
        [],
    ])

    with pytest.raises(AppError) as error:
        get_supplier(
            make_user(),
            db,
            uuid4(),
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Supplier not found"

def test_list_applies_search_and_status_filters():
    db = FakeDB([
        [make_supplier()],
    ])

    list_suppliers(
        make_user(),
        db,
        search="  ac  ",
        is_active=True,
    )

    statement = db.statements[0]

    assert "%ac%" in statement.compile().params.values()
    assert "is_active" in str(statement.whereclause)

def test_list_without_filters_sends_no_bound_parameters():
    db = FakeDB([
        [make_supplier()],
    ])

    list_suppliers(
        make_user(),
        db,
    )

    assert db.statements[0].compile().params == {}

def test_rejects_payload_with_no_fields_set():
    db = FakeDB([
        [make_supplier()],
    ])

    with pytest.raises(AppError) as error:
        update_supplier(
            SupplierUpdate(),
            make_user(),
            db,
            uuid4(),
        )

    assert error.value.status_code == 400
    assert error.value.detail == "No fields to update"
    assert db.commits == 0

def test_rejects_name_held_by_another_active_supplier():
    db = FakeDB([
        [make_supplier()],
        [{"id": uuid4()}],
    ])

    with pytest.raises(AppError) as error:
        update_supplier(
            SupplierUpdate(nombre="Otro"),
            make_user(),
            db,
            uuid4(),
        )

    assert error.value.status_code == 400
    assert error.value.detail == "Supplier name already exists"
    assert db.commits == 0

def test_writes_only_fields_that_were_sent():
    supplier = make_supplier()

    db = FakeDB([
        [supplier],
        [],
        [supplier],
    ])

    update_supplier(
        SupplierUpdate(
            telefono="5555-0102",
        ),
        make_user(),
        db,
        supplier["id"],
    )

    assert written_columns(db.statements[1]) == {
        "telefono",
        "updated_at",
    }

    assert db.commits == 1

def test_keeps_current_name_available_to_same_supplier():
    supplier = make_supplier()

    db = FakeDB([
        [supplier],
        [],
        [],
        [supplier],
    ])

    update_supplier(
        SupplierUpdate(nombre="Acme"),
        make_user(),
        db,
        supplier["id"],
    )

    assert db.commits == 1

def test_rejects_setting_status_it_already_has():
    db = FakeDB([
        [make_supplier(is_active=True)],
    ])

    with pytest.raises(AppError) as error:
        update_supplier_status(
            make_user(),
            db,
            uuid4(),
            True,
        )

    assert error.value.status_code == 400
    assert error.value.detail == "Supplier already has this status"
    assert db.commits == 0

def test_refuses_to_deactivate_while_active_products_reference_it():
    db = FakeDB([
        [make_supplier(is_active=True)],
        [{"id": uuid4()}],
    ])

    with pytest.raises(AppError) as error:
        update_supplier_status(
            make_user(),
            db,
            uuid4(),
            False,
        )

    assert error.value.status_code == 400
    assert error.value.detail == "Supplier still has active products"
    assert db.commits == 0

def test_deactivates_when_no_active_product_references_supplier():
    supplier_id = uuid4()

    inactive_supplier = make_supplier(
        is_active=False,
    )

    db = FakeDB([
        [make_supplier(is_active=True)],
        [],
        [],
        [inactive_supplier],
    ])

    result = update_supplier_status(
        make_user(),
        db,
        supplier_id,
        False,
    )

    assert result["is_active"] is False
    assert db.commits == 1

    assert written_columns(db.statements[2]) == {
        "is_active",
        "updated_at",
    }

def test_reactivating_skips_active_products_check():
    db = FakeDB([
        [make_supplier(is_active=False)],
        [],  # name availability guard
        [],  # update
        [make_supplier(is_active=True)],
    ])

    result = update_supplier_status(
        make_user(),
        db,
        uuid4(),
        True,
    )

    assert result["is_active"] is True
    assert db.commits == 1

def test_does_nothing_when_supplier_is_already_inactive():
    db = FakeDB([
        [make_supplier(is_active=False)],
    ])

    result = delete_supplier(
        make_user(),
        db,
        uuid4(),
    )

    assert result is None
    assert db.commits == 0

def test_refuses_to_delete_while_active_products_reference_supplier():
    db = FakeDB([
        [make_supplier(is_active=True)],
        [{"id": uuid4()}],
    ])

    with pytest.raises(AppError) as error:
        delete_supplier(
            make_user(),
            db,
            uuid4(),
        )

    assert error.value.status_code == 400
    assert error.value.detail == "Supplier still has active products"
    assert db.commits == 0

def test_soft_deletes_supplier():
    db = FakeDB([
        [make_supplier(is_active=True)],
        [],
        [],
    ])

    delete_supplier(
        make_user(),
        db,
        uuid4(),
    )

    assert db.commits == 1

    assert (
        db.statements[2]
        .compile()
        .params["is_active"]
        is False
    )

def test_rejects_user_without_company():
    user = SimpleNamespace(company_id=None, company=None,)

    with pytest.raises(AppError) as error:
        list_suppliers(user, FakeDB(),)

    assert error.value.status_code == 403

def test_rejects_user_whose_company_is_inactive():
    user = SimpleNamespace(
        company_id=uuid4(),
        company=SimpleNamespace(is_active=False, schema_name=SCHEMA_NAME,),
    )

    with pytest.raises(AppError) as error:
        list_suppliers(user, FakeDB(),)

    assert error.value.status_code == 403

def test_queries_are_scoped_to_company_schema():
    db = FakeDB([[make_supplier()],])

    list_suppliers(make_user(), db,)

    assert SCHEMA_NAME in str(db.statements[0])


def test_reactivating_is_refused_when_the_name_was_taken():
    """Only active suppliers reserve a name, so the freed one may be gone."""
    db = FakeDB([
        [make_supplier(is_active=False)],
        [{"id": uuid4()}],  # another active supplier already holds the name
    ])

    with pytest.raises(AppError) as error:
        update_supplier_status(
            make_user(),
            db,
            uuid4(),
            True,
        )

    assert error.value.status_code == 400
    assert "name" in error.value.detail.lower()
    assert db.commits == 0


def test_the_reactivation_guard_excludes_the_supplier_itself():
    supplier_id = uuid4()
    db = FakeDB([
        [make_supplier(is_active=False)],
        [],
        [],
        [make_supplier(is_active=True)],
    ])

    update_supplier_status(make_user(), db, supplier_id, True)

    guard = str(db.statements[1])

    assert "is_active IS true" in guard
    assert "id !=" in guard
