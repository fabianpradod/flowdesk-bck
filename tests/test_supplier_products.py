from types import SimpleNamespace
from uuid import uuid4
import pytest
from app.schemas.inventory import SupplierProductCreate, SupplierProductUpdate
from app.services.inventory import create_supplier_product, delete_supplier_product, get_supplier_product, list_supplier_products, update_supplier_product
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
    company = SimpleNamespace(is_active=True, schema_name=SCHEMA_NAME,)

    return SimpleNamespace(company_id=uuid4(), company=company,)

def make_supplier():
    return {
        "id": uuid4(),
        "nombre": "Acme",
        "correo": "acme@example.com",
        "telefono": "5555-0101",
        "is_active": True,
    }

def make_product():
    return {
        "id": uuid4(),
        "sku": "PROD-001",
        "nombre": "Producto 1",
        "descripcion": "Producto de prueba",
        "is_active": True,
    }

def make_supplier_product(supplier_id=None, product_id=None,):
    return {
        "id": uuid4(),
        "proveedor_id": supplier_id or uuid4(),
        "producto_id": product_id or uuid4(),
        "precio_cotizacion": "100.00",
        "descripcion": "Cotización de prueba",
        "is_active": True,
    }

def written_columns(statement):
    return {
        getattr(key, "name", key)
        for key in statement._values
    }

def test_create_supplier_product_persists_relationship():
    supplier = make_supplier()
    product = make_product()
    created = make_supplier_product(
        supplier_id=supplier["id"],
        product_id=product["id"],
    )

    db = FakeDB([
        [supplier],
        [product],
        [],
        [created],
    ])

    data = SupplierProductCreate(
        proveedor_id=supplier["id"],
        producto_id=product["id"],
        precio_cotizacion="125.50",
        descripcion="Nueva cotización",
    )

    result = create_supplier_product(
        data,
        make_user(),
        db,
    )

    assert result == created
    assert db.commits == 1

def test_create_supplier_product_rejects_nonexistent_supplier():
    product = make_product()

    db = FakeDB([[], [product],])

    data = SupplierProductCreate(
        proveedor_id=uuid4(),
        producto_id=product["id"],
        precio_cotizacion="100.00",
        descripcion=None,
    )

    with pytest.raises(AppError) as error:
        create_supplier_product(
            data,
            make_user(),
            db,
        )

    assert error.value.status_code == 404
    assert "Supplier" in error.value.detail
    assert db.commits == 0

def test_create_supplier_product_rejects_nonexistent_product():
    supplier = make_supplier()

    db = FakeDB([[supplier], [],])

    data = SupplierProductCreate(
        proveedor_id=supplier["id"],
        producto_id=uuid4(),
        precio_cotizacion="100.00",
        descripcion=None,
    )

    with pytest.raises(AppError) as error:
        create_supplier_product(
            data,
            make_user(),
            db,
        )

    assert error.value.status_code == 404
    assert "Product" in error.value.detail
    assert db.commits == 0

def test_create_supplier_product_rejects_duplicate_relationship():
    supplier = make_supplier()
    product = make_product()
    existing = make_supplier_product(supplier_id=supplier["id"], product_id=product["id"],)

    db = FakeDB([[supplier], [product], [existing],])

    data = SupplierProductCreate(
        proveedor_id=supplier["id"],
        producto_id=product["id"],
        precio_cotizacion="100.00",
        descripcion="Duplicado",
    )

    with pytest.raises(AppError) as error:
        create_supplier_product(
            data,
            make_user(),
            db,
        )

    assert error.value.status_code == 400
    assert "already exists" in error.value.detail
    assert db.commits == 0

def test_get_supplier_product_returns_relationship():
    relationship = make_supplier_product()

    db = FakeDB([[relationship],])

    result = get_supplier_product(
        make_user(),
        db,
        relationship["id"],
    )

    assert result == relationship

def test_get_supplier_product_returns_404_when_not_found():
    db = FakeDB([[],])

    with pytest.raises(AppError) as error:
        get_supplier_product(
            make_user(),
            db,
            uuid4(),
        )

    assert error.value.status_code == 404
    assert "Supplier product" in error.value.detail

def test_list_supplier_products_returns_rows():
    supplier_product = make_supplier_product()

    db = FakeDB([[supplier_product],])

    result = list_supplier_products(
        make_user(),
        db,
    )

    assert result == [supplier_product]

def test_list_supplier_products_can_filter_by_supplier():
    supplier_id = uuid4()

    db = FakeDB([[make_supplier_product(supplier_id=supplier_id)],])

    list_supplier_products(
        make_user(),
        db,
        proveedor_id=supplier_id,
    )

    statement = db.statements[0]

    assert str(supplier_id) in str(statement.compile().params.values())

def test_list_supplier_products_can_filter_by_product():
    product_id = uuid4()

    db = FakeDB([[make_supplier_product(product_id=product_id)],])

    list_supplier_products(
        make_user(),
        db,
        producto_id=product_id,
    )

    statement = db.statements[0]

    assert str(product_id) in str(statement.compile().params.values())

def test_update_supplier_product_updates_only_sent_fields():
    relationship = make_supplier_product()

    db = FakeDB([[relationship],[relationship],])

    data = SupplierProductUpdate(precio_cotizacion="150.00",)

    result = update_supplier_product(
        data,
        make_user(),
        db,
        relationship["id"],
    )

    assert result == relationship
    assert db.commits == 1

    assert written_columns(db.statements[1]) == {
        "precio_cotizacion",
        "updated_at",
    }

def test_update_supplier_product_rejects_empty_payload():
    relationship = make_supplier_product()

    db = FakeDB([[relationship],])

    data = SupplierProductUpdate()

    with pytest.raises(AppError) as error:
        update_supplier_product(
            data,
            make_user(),
            db,
            relationship["id"],
        )

    assert error.value.status_code == 400
    assert db.commits == 0

def test_update_supplier_product_returns_404_when_not_found():
    db = FakeDB([[],])

    data = SupplierProductUpdate(precio_cotizacion="150.00",)

    with pytest.raises(AppError) as error:
        update_supplier_product(
            data,
            make_user(),
            db,
            uuid4(),
        )

    assert error.value.status_code == 404
    assert db.commits == 0

def test_delete_supplier_product_soft_deletes_relationship():
    relationship = make_supplier_product()

    db = FakeDB([[relationship], [relationship],])

    result = delete_supplier_product(make_user(), db, relationship["id"],)

    assert result is None
    assert db.commits == 1

    assert db.statements[1].compile().params["is_active"] is False

def test_delete_supplier_product_returns_404_when_not_found():
    db = FakeDB([
        [],
    ])

    with pytest.raises(AppError) as error:
        delete_supplier_product(make_user(), db, uuid4(),)

    assert error.value.status_code == 404
    assert db.commits == 0

def test_supplier_products_reject_user_without_company():
    user = SimpleNamespace(company_id=None, company=None,)

    with pytest.raises(AppError) as error:
        list_supplier_products(user, FakeDB(),)

    assert error.value.status_code == 403

def test_supplier_products_reject_inactive_company():
    user = SimpleNamespace(
        company_id=uuid4(),
        company=SimpleNamespace(is_active=False, schema_name=SCHEMA_NAME,),
    )

    with pytest.raises(AppError) as error:
        list_supplier_products( user, FakeDB(),)

    assert error.value.status_code == 403

def test_supplier_products_are_scoped_to_tenant_schema():
    db = FakeDB([[make_supplier_product()],])

    list_supplier_products(make_user(), db,)

    assert SCHEMA_NAME in str(db.statements[0])