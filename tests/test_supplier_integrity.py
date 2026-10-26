"""Supplier names stay unique among active suppliers, also under concurrent writes."""
import pytest
from sqlalchemy import func, select

from app.schemas.inventory import SupplierCreate, SupplierUpdate
from app.services import inventory as inventory_service
from app.utils.exceptions import AppError
from tests.tenant_sqlite import new_session, tenant_engine, tenant_user


@pytest.fixture
def tenant():
    engine, tables = tenant_engine()
    return engine, tables, tenant_user()


def _create(engine, user, nombre):
    with new_session(engine) as db:
        return inventory_service.create_supplier(SupplierCreate(nombre=nombre), user, db)


def _active_named(engine, tables, nombre):
    suppliers = tables["proveedor"]
    with new_session(engine) as db:
        return db.execute(
            select(func.count()).select_from(suppliers).where(
                func.lower(suppliers.c.nombre) == nombre.lower(),
                suppliers.c.is_active.is_(True),
            )
        ).scalar_one()


@pytest.mark.parametrize(("existing", "new"), [("1000 Tornillos", "100%"), ("ABC", "A_C")])
def test_like_wildcards_in_a_name_are_compared_literally(tenant, existing, new):
    engine, _tables, user = tenant
    _create(engine, user, existing)

    assert _create(engine, user, new)["nombre"] == new


def test_name_check_ignores_case(tenant):
    engine, _tables, user = tenant
    _create(engine, user, "Acme")

    with pytest.raises(AppError) as exc:
        _create(engine, user, "ACME")

    assert exc.value.status_code == 400
    assert exc.value.message == "Supplier name already exists"
