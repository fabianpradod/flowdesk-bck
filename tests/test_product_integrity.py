"""SKUs are unique per company regardless of case or of which path created them."""
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import insert, select

from app.schemas.inventory import ProductCreate
from app.services import inventory as inventory_service
from app.utils.exceptions import AppError, ProductImportError
from tests.tenant_sqlite import NOW, new_session, tenant_engine, tenant_user


@pytest.fixture
def tenant():
    engine, tables = tenant_engine()
    return engine, tables, tenant_user()


def _csv(*skus):
    return ("sku,nombre\n" + "".join(f"{sku},Producto {index}\n" for index, sku in enumerate(skus))).encode()


def _import(engine, user, *skus):
    with new_session(engine) as db:
        return inventory_service.import_products_from_file("productos.csv", _csv(*skus), user, db)


def _create(engine, user, sku):
    with new_session(engine) as db:
        return inventory_service.create_product(ProductCreate(sku=sku, nombre="Producto"), user, db)


def _skus(engine, tables):
    products = tables["producto"]
    with new_session(engine) as db:
        return sorted(db.execute(select(products.c.sku)).scalars())


def _insert_legacy(engine, tables, sku):
    with new_session(engine) as db:
        db.execute(insert(tables["producto"]).values(
            id=uuid4(), sku=sku, nombre="Legacy", stock_actual=Decimal("0"), created_at=NOW, updated_at=NOW,
        ))
        db.commit()


def test_import_stores_skus_in_lowercase_like_product_create(tenant):
    engine, tables, user = tenant

    result = _import(engine, user, "ABC-1")

    assert result["products"][0]["sku"] == "abc-1"
    assert _skus(engine, tables) == ["abc-1"]


def test_import_flags_skus_that_differ_only_in_case_within_the_file(tenant):
    engine, tables, user = tenant

    with pytest.raises(ProductImportError) as exc:
        _import(engine, user, "ABC-1", "abc-1")

    assert [error["code"] for error in exc.value.errors] == ["duplicate_sku"]
    assert _skus(engine, tables) == []


def test_import_refuses_a_sku_created_before_with_other_case(tenant):
    engine, tables, user = tenant
    _create(engine, user, "abc-1")

    with pytest.raises(ProductImportError) as exc:
        _import(engine, user, "ABC-1")

    assert exc.value.errors == [{"row": 2, "column": "sku", "code": "existing_sku", "message": "SKU already exists"}]
    assert _skus(engine, tables) == ["abc-1"]


def test_legacy_uppercase_skus_still_block_new_products(tenant):
    # Imports stored SKUs as typed until now, so a company can already have "LEG-1".
    engine, tables, user = tenant
    _insert_legacy(engine, tables, "LEG-1")

    with pytest.raises(AppError) as exc:
        _create(engine, user, "leg-1")
    assert exc.value.status_code == 400
    assert exc.value.message == "SKU already exists"

    with pytest.raises(ProductImportError) as exc:
        _import(engine, user, "leg-1")
    assert exc.value.errors[0]["code"] == "existing_sku"
    assert _skus(engine, tables) == ["LEG-1"]
