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


def _skip_name_check(monkeypatch):
    # Simulates another request that passed the same check at the same moment:
    # only the unique index can refuse the second write.
    monkeypatch.setattr(inventory_service, "_assert_supplier_name_available", lambda *_args, **_kwargs: None)


def test_concurrent_create_with_the_same_name_answers_400(tenant, monkeypatch):
    engine, tables, user = tenant
    _create(engine, user, "Acme")
    _skip_name_check(monkeypatch)

    with pytest.raises(AppError) as exc:
        _create(engine, user, "ACME")

    assert exc.value.status_code == 400
    assert exc.value.message == "Supplier name already exists"
    assert _active_named(engine, tables, "acme") == 1


def test_concurrent_rename_to_a_taken_name_answers_400(tenant, monkeypatch):
    engine, tables, user = tenant
    _create(engine, user, "Acme")
    beta = _create(engine, user, "Beta")
    _skip_name_check(monkeypatch)

    with pytest.raises(AppError) as exc:
        with new_session(engine) as db:
            inventory_service.update_supplier(SupplierUpdate(nombre="acme"), user, db, beta["id"])

    assert exc.value.status_code == 400
    assert _active_named(engine, tables, "beta") == 1


def test_concurrent_reactivation_of_a_taken_name_answers_400(tenant, monkeypatch):
    engine, tables, user = tenant
    old = _create(engine, user, "Acme")
    with new_session(engine) as db:
        inventory_service.update_supplier_status(user, db, old["id"], False)
    _create(engine, user, "Acme")
    _skip_name_check(monkeypatch)

    with pytest.raises(AppError) as exc:
        with new_session(engine) as db:
            inventory_service.update_supplier_status(user, db, old["id"], True)

    assert exc.value.status_code == 400
    assert _active_named(engine, tables, "acme") == 1


def test_inactive_suppliers_do_not_reserve_their_name(tenant):
    engine, tables, user = tenant
    for _round in range(2):
        supplier = _create(engine, user, "Acme")
        with new_session(engine) as db:
            inventory_service.update_supplier_status(user, db, supplier["id"], False)

    _create(engine, user, "Acme")

    assert _active_named(engine, tables, "acme") == 1
