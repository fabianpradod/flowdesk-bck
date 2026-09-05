from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO
from uuid import uuid4
import pytest
import zipfile
from sqlalchemy import Boolean, Column, DateTime, MetaData, Numeric, String, Table, create_engine, insert, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.types import TypeDecorator
from pydantic import ValidationError
from app.schemas.inventory import AnalyticsPeriod, AnalyticsWindow, InventoryMovementCreate, MovementType, ProductCreate, SupplierCreate, SupplierProductCreate, SupplierProductUpdate
from app.services import inventory as inventory_service
from app.utils.exceptions import AppError, ProductImportError

class UUIDString(TypeDecorator):
    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None

        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None

        return str(value)

@pytest.fixture
def inventory_db(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
    )

    metadata = MetaData()

    proveedor = Table(
        "proveedor",
        metadata,
        Column("id", UUIDString(), primary_key=True),
        Column("nombre", String(150), nullable=False),
        Column("telefono", String(50)),
        Column("correo", String(150)),
        Column("direccion", String(250)),
        Column("is_active", Boolean, nullable=False, default=True),
        Column("created_at", DateTime),
        Column("updated_at", DateTime),
    )

    producto = Table(
        "producto",
        metadata,
        Column("id", UUIDString(), primary_key=True),
        Column("proveedor_id", UUIDString(), nullable=True),
        Column("sku", String(100), nullable=False),
        Column("nombre", String(150), nullable=False),
        Column("descripcion", String(500)),
        Column("precio_venta", Numeric(18, 2)),
        Column("stock_actual", Numeric(18, 2), nullable=False),
        Column("stock_minimo", Numeric(18, 2), nullable=False),
        Column("unidad_medida", String(50)),
        Column("is_active", Boolean, nullable=False, default=True),
        Column("created_at", DateTime),
        Column("updated_at", DateTime),
    )

    proveedor_producto = Table(
        "proveedor_producto",
        metadata,
        Column("id", UUIDString(), primary_key=True),
        Column("proveedor_id", UUIDString(), nullable=False),
        Column("producto_id", UUIDString(), nullable=False),
        Column("precio_cotizacion", Numeric(18, 2)),
        Column("descripcion", String(500)),
        Column("is_active", Boolean, nullable=False, default=True),
        Column("created_at", DateTime),
        Column("updated_at", DateTime),
    )

    movimiento_inventario = Table(
        "movimiento_inventario",
        metadata,
        Column("id", UUIDString(), primary_key=True),
        Column("producto_id", UUIDString(), nullable=False),
        Column("usuario_id", UUIDString(), nullable=True),
        Column("tipo_movimiento", String(100), nullable=False),
        Column("fecha", DateTime, nullable=False),
        Column("cantidad", Numeric(18, 2), nullable=False),
        Column("stock_anterior", Numeric(18, 2), nullable=False),
        Column("stock_resultante", Numeric(18, 2), nullable=False),
        Column("motivo", String(500)),
        Column("referencia_tipo", String(100)),
        Column("referencia_id", UUIDString(), nullable=True),
    )

    alerta = Table(
        "alerta",
        metadata,
        Column("id", UUIDString(), primary_key=True),
        Column("producto_id", UUIDString(), nullable=False),
        Column("tipo", String(50), nullable=False),
        Column("mensaje", String(500)),
        Column("fecha", DateTime),
        Column("estado", String(50)),
        Column("resuelta_en", DateTime),
    )

    metadata.create_all(engine)

    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    db = SessionLocal()

    tables = {
        "proveedor": proveedor,
        "producto": producto,
        "proveedor_producto": proveedor_producto,
        "movimiento_inventario": movimiento_inventario,
        "alerta": alerta,
    }

    monkeypatch.setattr(
        inventory_service,
        "_get_tenant_tables_for_user",
        lambda _user: tables,
    )

    current_user = type(
        "TestUser",
        (),
        {"id": uuid4()},
    )()

    yield db, tables, current_user

    db.close()
    engine.dispose()

def _id(value):
    return str(value)

def _insert_supplier(
    db,
    tables,
    *,
    supplier_id=None,
    nombre="Proveedor Demo",
    is_active=True,
):
    supplier_id = supplier_id or uuid4()

    db.execute(
        insert(tables["proveedor"]).values(
            id=_id(supplier_id),
            nombre=nombre,
            telefono="55555555",
            correo="supplier@test.com",
            direccion="Guatemala",
            is_active=is_active,
            updated_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    return supplier_id

def _insert_product(
    db,
    tables,
    *,
    product_id=None,
    supplier_id=None,
    sku="SKU-001",
    nombre="Producto Demo",
    stock=Decimal("10"),
    minimo=Decimal("5"),
    is_active=True,
):
    product_id = product_id or uuid4()

    db.execute(
        insert(tables["producto"]).values(
            id=_id(product_id),
            proveedor_id=_id(supplier_id) if supplier_id else None,
            sku=sku,
            nombre=nombre,
            descripcion="Producto de prueba",
            precio_venta=Decimal("25.50"),
            stock_actual=stock,
            stock_minimo=minimo,
            unidad_medida="unidad",
            is_active=is_active,
            updated_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    return product_id

def _insert_movement(
    db,
    tables,
    *,
    product_id,
    movement_type="entrada_compra",
    quantity=Decimal("5"),
    stock_result=Decimal("15"),
    when=None,
):
    movement_id = uuid4()

    db.execute(
        insert(tables["movimiento_inventario"]).values(
            id=_id(movement_id),
            producto_id=_id(product_id),
            usuario_id=None,
            tipo_movimiento=movement_type,
            fecha=when or datetime.now(timezone.utc),
            cantidad=quantity,
            stock_anterior=Decimal("10"),
            stock_resultante=stock_result,
            motivo="Prueba",
            referencia_tipo=None,
            referencia_id=None,
        )
    )
    db.commit()

    return movement_id

def test_list_suppliers(inventory_db):
    db, tables, user = inventory_db

    _insert_supplier(db, tables, nombre="Alpha")
    _insert_supplier(db, tables, nombre="Beta")

    result = inventory_service.list_suppliers(
        user,
        db,
    )

    assert [item["nombre"] for item in result] == [
        "Alpha",
        "Beta",
    ]

def test_list_suppliers_search(inventory_db):
    db, tables, user = inventory_db

    _insert_supplier(db, tables, nombre="Proveedor Especial")
    _insert_supplier(db, tables, nombre="Otro")

    result = inventory_service.list_suppliers(
        user,
        db,
        search="especial",
    )

    assert len(result) == 1
    assert result[0]["nombre"] == "Proveedor Especial"

def test_list_suppliers_active_filter(inventory_db):
    db, tables, user = inventory_db

    _insert_supplier(
        db,
        tables,
        nombre="Activo",
        is_active=True,
    )
    _insert_supplier(
        db,
        tables,
        nombre="Inactivo",
        is_active=False,
    )

    result = inventory_service.list_suppliers(
        user,
        db,
        is_active=False,
    )

    assert len(result) == 1
    assert result[0]["nombre"] == "Inactivo"

def test_get_supplier(inventory_db):
    db, tables, user = inventory_db

    supplier_id = _insert_supplier(
        db,
        tables,
    )

    result = inventory_service.get_supplier(
        user,
        db,
        supplier_id,
    )

    assert result["id"] == _id(supplier_id)

def test_get_supplier_not_found(inventory_db):
    db, tables, user = inventory_db

    with pytest.raises(AppError) as exc:
        inventory_service.get_supplier(
            user,
            db,
            uuid4(),
        )

    assert exc.value.status_code == 404

def test_create_supplier(inventory_db):
    db, tables, user = inventory_db

    result = inventory_service.create_supplier(
        SupplierCreate(
            nombre="  Nuevo Proveedor  ",
            telefono="123",
            correo="supplier@example.com",
            direccion="Guatemala",
        ),
        user,
        db,
    )

    assert result["nombre"] == "Nuevo Proveedor"

def test_create_supplier_duplicate_name(inventory_db):
    db, tables, user = inventory_db

    _insert_supplier(
        db,
        tables,
        nombre="Proveedor Único",
    )

    with pytest.raises(AppError) as exc:
        inventory_service.create_supplier(
            SupplierCreate(
                nombre="Proveedor Único",
            ),
            user,
            db,
        )

    assert exc.value.status_code == 400

def test_create_supplier_duplicate_name_case_insensitive(inventory_db):
    db, tables, user = inventory_db

    _insert_supplier(
        db,
        tables,
        nombre="Proveedor",
    )

    with pytest.raises(AppError):
        inventory_service.create_supplier(
            SupplierCreate(
                nombre="PROVEEDOR",
            ),
            user,
            db,
        )

def test_update_supplier(inventory_db):
    db, tables, user = inventory_db

    supplier_id = _insert_supplier(
        db,
        tables,
        nombre="Original",
    )

    result = inventory_service.update_supplier(
        SupplierCreate(
            nombre="Nuevo",
        ),
        user,
        db,
        supplier_id,
    )

    assert result["nombre"] == "Nuevo"

def test_update_supplier_not_found(inventory_db):
    db, tables, user = inventory_db

    with pytest.raises(AppError) as exc:
        inventory_service.update_supplier(
            SupplierCreate(nombre="Nuevo"),
            user,
            db,
            uuid4(),
        )

    assert exc.value.status_code == 404

def test_update_supplier_without_fields(inventory_db):
    db, tables, user = inventory_db

    supplier_id = _insert_supplier(
        db,
        tables,
    )

    class EmptyUpdate:
        def model_dump(self, **kwargs):
            return {}

    with pytest.raises(AppError) as exc:
        inventory_service.update_supplier(
            EmptyUpdate(),
            user,
            db,
            supplier_id,
        )

    assert exc.value.status_code == 400

def test_update_supplier_duplicate_name(inventory_db):
    db, tables, user = inventory_db

    first = _insert_supplier(
        db,
        tables,
        nombre="First",
    )

    _insert_supplier(
        db,
        tables,
        nombre="Second",
    )

    with pytest.raises(AppError) as exc:
        inventory_service.update_supplier(
            SupplierCreate(nombre="Second"),
            user,
            db,
            first,
        )

    assert exc.value.status_code == 400

def test_update_supplier_status(inventory_db):
    db, tables, user = inventory_db

    supplier_id = _insert_supplier(
        db,
        tables,
    )

    result = inventory_service.update_supplier_status(
        user,
        db,
        supplier_id,
        False,
    )

    assert result["is_active"] is False

def test_update_supplier_status_same_status(inventory_db):
    db, tables, user = inventory_db

    supplier_id = _insert_supplier(
        db,
        tables,
        is_active=True,
    )

    with pytest.raises(AppError) as exc:
        inventory_service.update_supplier_status(
            user,
            db,
            supplier_id,
            True,
        )

    assert exc.value.status_code == 400

def test_update_supplier_status_inactive_with_active_product(inventory_db,):
    db, tables, user = inventory_db

    supplier_id = _insert_supplier(
        db,
        tables,
    )

    _insert_product(
        db,
        tables,
        supplier_id=supplier_id,
        is_active=True,
    )

    with pytest.raises(AppError) as exc:
        inventory_service.update_supplier_status(
            user,
            db,
            supplier_id,
            False,
        )

    assert exc.value.status_code == 400

def test_delete_supplier(inventory_db):
    db, tables, user = inventory_db

    supplier_id = _insert_supplier(
        db,
        tables,
    )

    inventory_service.delete_supplier(
        user,
        db,
        supplier_id,
    )

    row = db.execute(
        select(tables["proveedor"]).where(
            tables["proveedor"].c.id == _id(supplier_id)
        )
    ).mappings().one()

    assert row["is_active"] is False

def test_delete_supplier_already_inactive(inventory_db):
    db, tables, user = inventory_db

    supplier_id = _insert_supplier(
        db,
        tables,
        is_active=False,
    )

    result = inventory_service.delete_supplier(
        user,
        db,
        supplier_id,
    )

    assert result is None

def test_delete_supplier_with_active_product(inventory_db):
    db, tables, user = inventory_db

    supplier_id = _insert_supplier(
        db,
        tables,
    )

    _insert_product(
        db,
        tables,
        supplier_id=supplier_id,
    )

    with pytest.raises(AppError) as exc:
        inventory_service.delete_supplier(
            user,
            db,
            supplier_id,
        )

    assert exc.value.status_code == 400

def test_list_products(inventory_db):
    db, tables, user = inventory_db

    _insert_product(
        db,
        tables,
        sku="B",
        nombre="Beta",
    )
    _insert_product(
        db,
        tables,
        sku="A",
        nombre="Alpha",
    )

    result = inventory_service.list_products(
        user,
        db,
    )

    assert [item["nombre"] for item in result] == [
        "Alpha",
        "Beta",
    ]

def test_create_product(inventory_db):
    db, tables, user = inventory_db

    supplier_id = _insert_supplier(
        db,
        tables,
    )

    result = inventory_service.create_product(
        ProductCreate(
            sku=" SKU-100 ",
            nombre="  Producto Nuevo ",
            descripcion="Descripción",
            precio_venta=Decimal("50"),
            stock_minimo=Decimal("5"),
            unidad_medida=" unidad ",
            proveedor_id=supplier_id,
        ),
        user,
        db,
    )

    assert result["sku"] == "sku-100"
    assert result["nombre"] == "Producto Nuevo"
    assert result["unidad_medida"] == "unidad"

def test_create_product_without_supplier(inventory_db):
    db, tables, user = inventory_db

    result = inventory_service.create_product(
        ProductCreate(
            sku="SKU-NO-SUPPLIER",
            nombre="Producto",
            precio_venta=Decimal("10"),
            stock_minimo=Decimal("2"),
            unidad_medida="unidad",
        ),
        user,
        db,
    )

    assert result["proveedor_id"] is None

def test_create_product_supplier_not_found(inventory_db):
    db, tables, user = inventory_db

    with pytest.raises(AppError) as exc:
        inventory_service.create_product(
            ProductCreate(
                sku="SKU-1",
                nombre="Producto",
                proveedor_id=uuid4(),
            ),
            user,
            db,
        )

    assert exc.value.status_code == 404

def test_create_product_inactive_supplier(inventory_db):
    db, tables, user = inventory_db

    supplier_id = _insert_supplier(
        db,
        tables,
        is_active=False,
    )

    with pytest.raises(AppError) as exc:
        inventory_service.create_product(
            ProductCreate(
                sku="SKU-1",
                nombre="Producto",
                proveedor_id=supplier_id,
            ),
            user,
            db,
        )

    assert exc.value.status_code == 400

def test_create_product_duplicate_sku(inventory_db):
    db, tables, user = inventory_db

    _insert_product(
        db,
        tables,
        sku="duplicate",
    )

    with pytest.raises(AppError) as exc:
        inventory_service.create_product(
            ProductCreate(
                sku="DUPLICATE",
                nombre="Otro",
            ),
            user,
            db,
        )

    assert exc.value.status_code == 400

def test_update_product_status(inventory_db):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
        is_active=True,
    )

    result = inventory_service.update_product_status(
        user,
        db,
        product_id,
        False,
    )

    assert result["is_active"] is False

def test_update_product_status_same_status(inventory_db):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
        is_active=True,
    )

    with pytest.raises(AppError) as exc:
        inventory_service.update_product_status(
            user,
            db,
            product_id,
            True,
        )

    assert exc.value.status_code == 400

def test_update_product_status_not_found(inventory_db):
    db, tables, user = inventory_db

    with pytest.raises(AppError) as exc:
        inventory_service.update_product_status(
            user,
            db,
            uuid4(),
            False,
        )

    assert exc.value.status_code == 404

def test_create_supplier_product(inventory_db):
    db, tables, user = inventory_db

    supplier_id = _insert_supplier(
        db,
        tables,
    )
    product_id = _insert_product(
        db,
        tables,
    )

    result = inventory_service.create_supplier_product(
        SupplierProductCreate(
            proveedor_id=supplier_id,
            producto_id=product_id,
            precio_cotizacion=Decimal("15"),
            descripcion="Cotización",
        ),
        user,
        db,
    )

    assert result["proveedor_id"] == _id(supplier_id)
    assert result["producto_id"] == _id(product_id)

def test_create_supplier_product_supplier_not_found(inventory_db):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
    )

    with pytest.raises(AppError) as exc:
        inventory_service.create_supplier_product(
            SupplierProductCreate(
                proveedor_id=uuid4(),
                producto_id=product_id,
                precio_cotizacion=Decimal("10"),
            ),
            user,
            db,
        )

    assert exc.value.status_code == 404

def test_create_supplier_product_product_not_found(inventory_db):
    db, tables, user = inventory_db

    supplier_id = _insert_supplier(
        db,
        tables,
    )

    with pytest.raises(AppError) as exc:
        inventory_service.create_supplier_product(
            SupplierProductCreate(
                proveedor_id=supplier_id,
                producto_id=uuid4(),
                precio_cotizacion=Decimal("10"),
            ),
            user,
            db,
        )

    assert exc.value.status_code == 404

def test_create_supplier_product_duplicate(inventory_db):
    db, tables, user = inventory_db

    supplier_id = _insert_supplier(
        db,
        tables,
    )
    product_id = _insert_product(
        db,
        tables,
    )

    data = SupplierProductCreate(
        proveedor_id=supplier_id,
        producto_id=product_id,
        precio_cotizacion=Decimal("10"),
    )

    inventory_service.create_supplier_product(
        data,
        user,
        db,
    )

    with pytest.raises(AppError) as exc:
        inventory_service.create_supplier_product(
            data,
            user,
            db,
        )

    assert exc.value.status_code == 400

def test_get_supplier_product(inventory_db):
    db, tables, user = inventory_db

    supplier_id = _insert_supplier(db, tables)
    product_id = _insert_product(db, tables)

    created = inventory_service.create_supplier_product(
        SupplierProductCreate(
            proveedor_id=supplier_id,
            producto_id=product_id,
            precio_cotizacion=Decimal("10"),
        ),
        user,
        db,
    )

    result = inventory_service.get_supplier_product(
        user,
        db,
        created["id"],
    )

    assert result["id"] == created["id"]

def test_get_supplier_product_not_found(inventory_db):
    db, tables, user = inventory_db

    with pytest.raises(AppError) as exc:
        inventory_service.get_supplier_product(
            user,
            db,
            uuid4(),
        )

    assert exc.value.status_code == 404

def test_list_supplier_products(inventory_db):
    db, tables, user = inventory_db

    supplier_id = _insert_supplier(
        db,
        tables,
        nombre="Proveedor Alpha",
    )
    product_id = _insert_product(
        db,
        tables,
        nombre="Producto Alpha",
    )

    inventory_service.create_supplier_product(
        SupplierProductCreate(
            proveedor_id=supplier_id,
            producto_id=product_id,
            precio_cotizacion=Decimal("10"),
        ),
        user,
        db,
    )

    result = inventory_service.list_supplier_products(
        user,
        db,
    )

    assert len(result) == 1

def test_list_supplier_products_filters(inventory_db):
    db, tables, user = inventory_db

    supplier_id = _insert_supplier(
        db,
        tables,
        nombre="Proveedor Especial",
    )

    product_id = _insert_product(
        db,
        tables,
        nombre="Producto Especial",
    )

    inventory_service.create_supplier_product(
        SupplierProductCreate(
            proveedor_id=supplier_id,
            producto_id=product_id,
            precio_cotizacion=Decimal("10"),
        ),
        user,
        db,
    )

    result = inventory_service.list_supplier_products(
        user,
        db,
        proveedor_id=supplier_id,
        producto_id=product_id,
        search="especial",
        active_only=True,
    )

    assert len(result) == 1

def test_list_supplier_products_inactive_filter(inventory_db):
    supplier_id = None
    product_id = None

    db, tables, user = inventory_db

    supplier_id = _insert_supplier(db, tables)
    product_id = _insert_product(db, tables)

    created = inventory_service.create_supplier_product(
        SupplierProductCreate(
            proveedor_id=supplier_id,
            producto_id=product_id,
            precio_cotizacion=Decimal("10"),
        ),
        user,
        db,
    )

    inventory_service.delete_supplier_product(
        user,
        db,
        created["id"],
    )

    result = inventory_service.list_supplier_products(
        user,
        db,
        active_only=False,
    )

    assert len(result) == 1

def test_update_supplier_product(inventory_db):
    db, tables, user = inventory_db
    supplier_id = _insert_supplier(db, tables)
    product_id = _insert_product(db, tables)

    created = inventory_service.create_supplier_product(
        SupplierProductCreate(
            proveedor_id=supplier_id,
            producto_id=product_id,
            precio_cotizacion=Decimal("10"),
            descripcion="Original",
        ),
        user,
        db,
    )

    result = inventory_service.update_supplier_product(
        SupplierProductUpdate(
            precio_cotizacion=Decimal("20"),
            descripcion="Modificado",
        ),
        user,
        db,
        created["id"],
    )

    assert result["precio_cotizacion"] == Decimal("20")
    assert result["descripcion"] == "Modificado"

def test_update_supplier_product_ignores_relationship_ids(inventory_db,):
    db, tables, user = inventory_db
    supplier_id = _insert_supplier(db, tables)
    product_id = _insert_product(db, tables)

    created = inventory_service.create_supplier_product(
        SupplierProductCreate(
            proveedor_id=supplier_id,
            producto_id=product_id,
            precio_cotizacion=Decimal("10"),
        ),
        user,
        db,
    )

    class RelationshipUpdate:
        def model_dump(self, **kwargs):
            return {
                "proveedor_id": uuid4(),
                "producto_id": uuid4(),
                "precio_cotizacion": Decimal("30"),
            }

    result = inventory_service.update_supplier_product(
        RelationshipUpdate(),
        user,
        db,
        created["id"],
    )

    assert result["precio_cotizacion"] == Decimal("30")
    assert result["proveedor_id"] == _id(supplier_id)
    assert result["producto_id"] == _id(product_id)

def test_update_supplier_product_no_fields(inventory_db):
    db, tables, user = inventory_db
    supplier_id = _insert_supplier(db, tables)
    product_id = _insert_product(db, tables)

    created = inventory_service.create_supplier_product(
        SupplierProductCreate(
            proveedor_id=supplier_id,
            producto_id=product_id,
            precio_cotizacion=Decimal("10"),
        ),
        user,
        db,
    )

    class EmptyUpdate:
        def model_dump(self, **kwargs):
            return {}

    with pytest.raises(AppError) as exc:
        inventory_service.update_supplier_product(
            EmptyUpdate(),
            user,
            db,
            created["id"],
        )

    assert exc.value.status_code == 400

def test_update_supplier_product_only_relationship_ids(inventory_db,):
    db, tables, user = inventory_db
    supplier_id = _insert_supplier(db, tables)
    product_id = _insert_product(db, tables)

    created = inventory_service.create_supplier_product(
        SupplierProductCreate(
            proveedor_id=supplier_id,
            producto_id=product_id,
            precio_cotizacion=Decimal("10"),
        ),
        user,
        db,
    )

    class RelationshipOnlyUpdate:
        def model_dump(self, **kwargs):
            return {
                "proveedor_id": supplier_id,
                "producto_id": product_id,
            }

    with pytest.raises(AppError) as exc:
        inventory_service.update_supplier_product(
            RelationshipOnlyUpdate(),
            user,
            db,
            created["id"],
        )

    assert exc.value.status_code == 400

def test_update_supplier_product_not_found(inventory_db):
    db, tables, user = inventory_db

    with pytest.raises(AppError) as exc:
        inventory_service.update_supplier_product(
            SupplierProductUpdate(
                descripcion="x",
            ),
            user,
            db,
            uuid4(),
        )

    assert exc.value.status_code == 404

def test_delete_supplier_product(inventory_db):
    db, tables, user = inventory_db
    supplier_id = _insert_supplier(db, tables)
    product_id = _insert_product(db, tables)

    created = inventory_service.create_supplier_product(
        SupplierProductCreate(
            proveedor_id=supplier_id,
            producto_id=product_id,
            precio_cotizacion=Decimal("10"),
        ),
        user,
        db,
    )

    result = inventory_service.delete_supplier_product(
        user,
        db,
        created["id"],
    )

    assert result is None

    row = db.execute(
        select(tables["proveedor_producto"]).where(
            tables["proveedor_producto"].c.id == created["id"]
        )
    ).mappings().one()

    assert row["is_active"] is False

def test_delete_supplier_product_not_found(inventory_db):
    db, tables, user = inventory_db

    with pytest.raises(AppError) as exc:
        inventory_service.delete_supplier_product(
            user,
            db,
            uuid4(),
        )

    assert exc.value.status_code == 404

def test_parse_csv_valid():
    content = (
        "sku,nombre,descripcion,precio_venta,stock_minimo,unidad_medida\n"
        "SKU-1,Producto 1,Desc,10.50,2,unidad\n"
    ).encode()

    result = inventory_service.parse_product_import_file(
        "products.csv",
        content,
    )

    assert len(result) == 1
    assert result[0]["sku"] == "SKU-1"
    assert result[0]["precio_venta"] == Decimal("10.50")

def test_parse_csv_utf8_bom():
    content = (
        "\ufeffsku,nombre\n"
        "SKU-1,Producto\n"
    ).encode("utf-8")

    result = inventory_service.parse_product_import_file(
        "products.csv",
        content,
    )

    assert result[0]["sku"] == "SKU-1"

def test_parse_empty_file():
    with pytest.raises(ProductImportError) as exc:
        inventory_service.parse_product_import_file(
            "products.csv",
            b"",
        )

    assert exc.value.code == "empty_file"

def test_parse_unsupported_format():
    with pytest.raises(ProductImportError) as exc:
        inventory_service.parse_product_import_file(
            "products.txt",
            b"hello",
        )

    assert exc.value.code == "unsupported_format"

def test_parse_invalid_utf8():
    with pytest.raises(ProductImportError) as exc:
        inventory_service.parse_product_import_file(
            "products.csv",
            b"\xff\xfe\xfd",
        )

    assert exc.value.code == "invalid_format"

def test_parse_csv_missing_required_column():
    content = (
        "sku,descripcion\n"
        "SKU-1,Desc\n"
    ).encode()

    with pytest.raises(ProductImportError) as exc:
        inventory_service.parse_product_import_file(
            "products.csv",
            content,
        )

    assert exc.value.code == "invalid_columns"

def test_parse_csv_unexpected_column():
    content = (
        "sku,nombre,not_allowed\n"
        "SKU-1,Producto,value\n"
    ).encode()

    with pytest.raises(ProductImportError) as exc:
        inventory_service.parse_product_import_file(
            "products.csv",
            content,
        )

    assert exc.value.code == "invalid_columns"

def test_parse_csv_required_values():
    content = (
        "sku,nombre\n"
        ",Producto\n"
        "SKU-2,\n"
    ).encode()

    with pytest.raises(ProductImportError) as exc:
        inventory_service.parse_product_import_file(
            "products.csv",
            content,
        )

    assert exc.value.code == "invalid_rows"

def test_parse_csv_duplicate_sku():
    content = (
        "sku,nombre\n"
        "SKU-1,Producto 1\n"
        "SKU-1,Producto 2\n"
    ).encode()

    with pytest.raises(ProductImportError) as exc:
        inventory_service.parse_product_import_file(
            "products.csv",
            content,
        )

    assert exc.value.code == "invalid_rows"

def test_parse_csv_negative_decimal():
    content = (
        "sku,nombre,precio_venta\n"
        "SKU-1,Producto,-10\n"
    ).encode()

    with pytest.raises(ProductImportError) as exc:
        inventory_service.parse_product_import_file(
            "products.csv",
            content,
        )

    assert exc.value.code == "invalid_rows"

def test_parse_csv_invalid_decimal():
    content = (
        "sku,nombre,precio_venta\n"
        "SKU-1,Producto,abc\n"
    ).encode()

    with pytest.raises(ProductImportError) as exc:
        inventory_service.parse_product_import_file(
            "products.csv",
            content,
        )

    assert exc.value.code == "invalid_rows"

def test_parse_csv_invalid_uuid():
    content = (
        "sku,nombre,proveedor_id\n"
        "SKU-1,Producto,not-a-uuid\n"
    ).encode()

    with pytest.raises(ProductImportError) as exc:
        inventory_service.parse_product_import_file(
            "products.csv",
            content,
        )

    assert exc.value.code == "invalid_rows"

def test_parse_csv_blank_optional_values():
    content = (
        "sku,nombre,descripcion,precio_venta,stock_minimo,unidad_medida\n"
        "SKU-1,Producto,,, ,\n"
    ).encode()

    result = inventory_service.parse_product_import_file(
        "products.csv",
        content,
    )

    assert result[0]["descripcion"] is None
    assert result[0]["precio_venta"] == Decimal("0")
    assert result[0]["stock_minimo"] == Decimal("0")
    assert result[0]["unidad_medida"] == "unidad"

def test_parse_csv_injection_is_rejected():
    content = (
        "sku,nombre\n"
        "=CMD,Producto\n"
    ).encode()

    with pytest.raises(ProductImportError) as exc:
        inventory_service.parse_product_import_file(
            "products.csv",
            content,
        )

    assert exc.value.code == "invalid_rows"

def test_import_products_success(inventory_db):
    db, tables, user = inventory_db

    content = (
        "sku,nombre,descripcion,precio_venta,stock_minimo,unidad_medida\n"
        "SKU-1,Producto 1,Desc,10,2,unidad\n"
        "SKU-2,Producto 2,Desc,20,5,caja\n"
    ).encode()

    result = inventory_service.import_products_from_file(
        "products.csv",
        content,
        user,
        db,
    )

    assert result["inserted"] == 2
    assert len(result["products"]) == 2

def test_import_products_existing_sku(inventory_db):
    db, tables, user = inventory_db

    _insert_product(
        db,
        tables,
        sku="sku-1",
    )

    content = (
        "sku,nombre\n"
        "sku-1,Producto\n"
    ).encode()

    with pytest.raises(ProductImportError) as exc:
        inventory_service.import_products_from_file(
            "products.csv",
            content,
            user,
            db,
        )

    assert exc.value.code == "invalid_rows"

def test_import_products_supplier_not_found(inventory_db):
    db, tables, user = inventory_db

    content = (
        "sku,nombre,proveedor_id\n"
        f"SKU-1,Producto,{uuid4()}\n"
    ).encode()

    with pytest.raises(ProductImportError) as exc:
        inventory_service.import_products_from_file(
            "products.csv",
            content,
            user,
            db,
        )

    assert exc.value.code == "invalid_rows"

def test_import_products_inactive_supplier(inventory_db):
    db, tables, user = inventory_db

    supplier_id = _insert_supplier(
        db,
        tables,
        is_active=False,
    )

    content = (
        "sku,nombre,proveedor_id\n"
        f"SKU-1,Producto,{supplier_id}\n"
    ).encode()

    with pytest.raises(ProductImportError) as exc:
        inventory_service.import_products_from_file(
            "products.csv",
            content,
            user,
            db,
        )

    assert exc.value.code == "invalid_rows"

def test_import_too_many_rows(monkeypatch):
    rows = [
        {
            "sku": f"SKU-{i}",
            "nombre": f"Product {i}",
        }
        for i in range(5001)
    ]

    with pytest.raises(ProductImportError) as exc:
        inventory_service._validate_import_size(rows)

    assert exc.value.code == "import_too_large"

@pytest.mark.parametrize(
    "movement_type",
    [
        "entrada_compra",
        "entrada_manual",
        "ajuste_positivo",
        "devolucion_cliente",
    ],
)
def test_movement_direction_inbound(movement_type):
    assert (
        inventory_service._movement_direction(movement_type)
        == "in"
    )

@pytest.mark.parametrize(
    "movement_type",
    [
        "salida_venta",
        "salida_manual",
        "ajuste_negativo",
        "devolucion_proveedor",
    ],
)
def test_movement_direction_outbound(movement_type):
    assert (
        inventory_service._movement_direction(movement_type)
        == "out"
    )

def test_movement_direction_invalid():
    with pytest.raises(AppError) as exc:
        inventory_service._movement_direction(
            "invalid_movement"
        )

    assert exc.value.status_code == 400

def test_create_inventory_movement_inbound(inventory_db):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
        stock=Decimal("10"),
        minimo=Decimal("5"),
    )

    result = inventory_service.create_inventory_movement(
        InventoryMovementCreate(
            producto_id=product_id,
            tipo_movimiento="entrada_compra",
            cantidad=Decimal("5"),
            motivo="Compra",
        ),
        user,
        db,
    )

    assert result["cantidad"] == Decimal("5")
    assert result["stock_anterior"] == Decimal("10")
    assert result["stock_resultante"] == Decimal("15")

def test_create_inventory_movement_outbound(inventory_db):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
        stock=Decimal("10"),
    )

    result = inventory_service.create_inventory_movement(
        InventoryMovementCreate(
            producto_id=product_id,
            tipo_movimiento="salida_venta",
            cantidad=Decimal("3"),
        ),
        user,
        db,
    )

    assert result["stock_resultante"] == Decimal("7")

def test_create_inventory_movement_product_not_found(inventory_db,):
    db, tables, user = inventory_db

    with pytest.raises(AppError) as exc:
        inventory_service.create_inventory_movement(
            InventoryMovementCreate(
                producto_id=uuid4(),
                tipo_movimiento="entrada_manual",
                cantidad=Decimal("1"),
            ),
            user,
            db,
        )

    assert exc.value.status_code == 404

def test_create_inventory_movement_inactive_product(inventory_db,):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
        is_active=False,
    )

    with pytest.raises(AppError) as exc:
        inventory_service.create_inventory_movement(
            InventoryMovementCreate(
                producto_id=product_id,
                tipo_movimiento="entrada_manual",
                cantidad=Decimal("1"),
            ),
            user,
            db,
        )

    assert exc.value.status_code == 400

def test_create_inventory_movement_zero_quantity(inventory_db):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
    )

    with pytest.raises(ValidationError):
        InventoryMovementCreate(
            producto_id=product_id,
            tipo_movimiento=MovementType.ENTRADA_MANUAL,
            cantidad=Decimal("0"),
        )

def test_create_inventory_movement_insufficient_stock(inventory_db,):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
        stock=Decimal("2"),
    )

    with pytest.raises(AppError) as exc:
        inventory_service.create_inventory_movement(
            InventoryMovementCreate(
                producto_id=product_id,
                tipo_movimiento="salida_venta",
                cantidad=Decimal("5"),
            ),
            user,
            db,
        )

    assert exc.value.status_code == 400

def test_create_inventory_movement_max_quantity(inventory_db,):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
        stock=Decimal("0"),
    )

    with pytest.raises(AppError) as exc:
        inventory_service.create_inventory_movement(
            InventoryMovementCreate(
                producto_id=product_id,
                tipo_movimiento="entrada_manual",
                cantidad=Decimal("1000000000"),
            ),
            user,
            db,
        )

    assert exc.value.status_code == 400

def test_list_inventory_movements(inventory_db):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
    )

    _insert_movement(
        db,
        tables,
        product_id=product_id,
    )

    result = inventory_service.list_inventory_movements(
        user,
        db,
    )

    assert len(result) == 1

def test_list_inventory_movements_filtered(inventory_db):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
    )

    other_product = _insert_product(
        db,
        tables,
        sku="SKU-2",
    )

    _insert_movement(
        db,
        tables,
        product_id=product_id,
    )
    _insert_movement(
        db,
        tables,
        product_id=other_product,
    )

    result = inventory_service.list_inventory_movements(
        user,
        db,
        product_id=product_id,
    )

    assert len(result) == 1

def test_stock_alert_zero_stock(inventory_db):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
        stock=Decimal("1"),
        minimo=Decimal("5"),
    )

    inventory_service.create_inventory_movement(
        InventoryMovementCreate(
            producto_id=product_id,
            tipo_movimiento="salida_venta",
            cantidad=Decimal("1"),
        ),
        user,
        db,
    )

    alerts = inventory_service.list_inventory_alerts(
        user,
        db,
    )

    assert len(alerts) == 1
    assert alerts[0]["tipo"] == "sin_stock"

def test_stock_alert_low_stock(inventory_db):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
        stock=Decimal("10"),
        minimo=Decimal("5"),
    )

    inventory_service.create_inventory_movement(
        InventoryMovementCreate(
            producto_id=product_id,
            tipo_movimiento="salida_venta",
            cantidad=Decimal("6"),
        ),
        user,
        db,
    )

    alerts = inventory_service.list_inventory_alerts(
        user,
        db,
    )

    assert len(alerts) == 1
    assert alerts[0]["tipo"] == "stock_bajo"

def test_stock_alert_resolved_after_restock(inventory_db):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
        stock=Decimal("1"),
        minimo=Decimal("5"),
    )

    inventory_service.create_inventory_movement(
        InventoryMovementCreate(
            producto_id=product_id,
            tipo_movimiento="salida_venta",
            cantidad=Decimal("1"),
        ),
        user,
        db,
    )

    inventory_service.create_inventory_movement(
        InventoryMovementCreate(
            producto_id=product_id,
            tipo_movimiento="entrada_compra",
            cantidad=Decimal("10"),
        ),
        user,
        db,
    )

    alerts = inventory_service.list_inventory_alerts(
        user,
        db,
    )

    assert alerts == []

def test_list_inventory_alerts_all_statuses(inventory_db):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
    )

    now = datetime.now(timezone.utc)

    db.execute(
        insert(tables["alerta"]).values(
            id=_id(uuid4()),
            producto_id=_id(product_id),
            tipo="stock_bajo",
            mensaje="Open",
            fecha=now,
            estado="pendiente",
        )
    )

    db.execute(
        insert(tables["alerta"]).values(
            id=_id(uuid4()),
            producto_id=_id(product_id),
            tipo="stock_bajo",
            mensaje="Resolved",
            fecha=now,
            estado="resuelta",
        )
    )

    db.commit()

    result = inventory_service.list_inventory_alerts(
        user,
        db,
        open_only=False,
    )

    assert len(result) == 2

def test_summarize_inventory_metrics():
    products = [
        {
            "stock_actual": Decimal("0"),
            "stock_minimo": Decimal("5"),
            "is_active": True,
        },
        {
            "stock_actual": Decimal("3"),
            "stock_minimo": Decimal("5"),
            "is_active": True,
        },
        {
            "stock_actual": Decimal("10"),
            "stock_minimo": Decimal("5"),
            "is_active": True,
        },
        {
            "stock_actual": Decimal("0"),
            "stock_minimo": Decimal("5"),
            "is_active": False,
        },
    ]

    movements = [
        {
            "tipo_movimiento": "entrada_compra",
            "cantidad": Decimal("20"),
        },
        {
            "tipo_movimiento": "salida_venta",
            "cantidad": Decimal("7"),
        },
    ]

    result = inventory_service.summarize_inventory_metrics(
        products,
        movements,
    )

    assert result["entradas"] == Decimal("20")
    assert result["salidas"] == Decimal("7")
    assert result["sin_stock"] == 1
    assert result["stock_bajo"] == 1

def test_inventory_history_format():
    product_id = uuid4()

    row = {
        "id": uuid4(),
        "producto_id": product_id,
        "sku": "SKU",
        "nombre": "Producto",
        "tipo_movimiento": "salida_venta",
        "fecha": datetime.now(timezone.utc),
        "cantidad": 3,
        "stock_resultante": 7,
        "motivo": "Venta",
    }

    result = inventory_service.format_inventory_history_row(
        row,
    )

    assert result["direction"] == "out"
    assert result["cantidad"] == Decimal("3")
    assert result["stock_resultante"] == Decimal("7")

def test_list_inventory_history(inventory_db):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
        sku="SKU-HISTORY",
        nombre="History Product",
    )

    _insert_movement(
        db,
        tables,
        product_id=product_id,
        movement_type="salida_venta",
        quantity=Decimal("2"),
        stock_result=Decimal("8"),
    )

    result = inventory_service.list_inventory_history(
        user,
        db,
        limit=10,
    )

    assert len(result) == 1
    assert result[0]["sku"] == "SKU-HISTORY"

def test_list_inventory_history_product_filter(inventory_db):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
    )

    other = _insert_product(
        db,
        tables,
        sku="OTHER",
    )

    _insert_movement(
        db,
        tables,
        product_id=product_id,
    )
    _insert_movement(
        db,
        tables,
        product_id=other,
    )

    result = inventory_service.list_inventory_history(
        user,
        db,
        limit=10,
        product_id=product_id,
    )

    assert len(result) == 1

def test_list_inventory_history_movement_type_filter(inventory_db,):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
    )

    _insert_movement(
        db,
        tables,
        product_id=product_id,
        movement_type="entrada_compra",
    )
    _insert_movement(
        db,
        tables,
        product_id=product_id,
        movement_type="salida_venta",
    )

    result = inventory_service.list_inventory_history(
        user,
        db,
        limit=10,
        movement_type="entrada_compra",
    )

    assert len(result) == 1
    assert result[0]["tipo_movimiento"] == "entrada_compra"

def test_resolve_analytics_range_custom():
    result = inventory_service._resolve_analytics_range(
        "custom",
        date(2026, 1, 1),
        date(2026, 1, 10),
    )

    assert result["start"].date() == date(2026, 1, 1)
    assert result["end"].date() == date(2026, 1, 10)

def test_resolve_analytics_range_custom_missing_start():
    with pytest.raises(AppError) as exc:
        inventory_service._resolve_analytics_range(
            "custom",
            None,
            date(2026, 1, 10),
        )

    assert exc.value.status_code == 400

def test_resolve_analytics_range_ytd():
    now = datetime(
        2026,
        8,
        9,
        12,
        tzinfo=timezone.utc,
    )

    result = inventory_service._resolve_analytics_range(
        "ytd",
        None,
        None,
        now=now,
    )

    assert result["start"].date() == date(2026, 1, 1)

@pytest.mark.parametrize("period", ["7d", "30d", "90d", "6m", "12m"],)
def test_resolve_analytics_range_standard_periods(period):
    now = datetime(
        2026,
        8,
        9,
        tzinfo=timezone.utc,
    )

    result = inventory_service._resolve_analytics_range(
        period,
        None,
        None,
        now=now,
    )

    assert result["end"] == now
    assert result["start"] < result["end"]

def test_resolve_analytics_range_invalid_dates():
    with pytest.raises(AppError) as exc:
        inventory_service._resolve_analytics_range(
            "custom",
            date(2026, 8, 10),
            date(2026, 8, 9),
        )

    assert exc.value.status_code == 400

@pytest.mark.parametrize("window", ["day", "week", "month"],)
def test_bucket_start(window):
    value = datetime(
        2026,
        8,
        12,
        10,
        tzinfo=timezone.utc,
    )

    result = inventory_service._bucket_start(
        value,
        window,
    )

    assert isinstance(result, date)

def test_bucket_labels():
    value = date(2026, 8, 3)

    assert (
        inventory_service._bucket_label(value, "month")
        == "2026-08"
    )

    assert (
        inventory_service._bucket_label(value, "week")
        == "2026-08-03 week"
    )

    assert (
        inventory_service._bucket_label(value, "day")
        == "2026-08-03"
    )

def test_date_to_datetime_start():
    result = inventory_service._date_to_datetime(
        date(2026, 8, 9),
    )

    assert result.hour == 0
    assert result.minute == 0

def test_date_to_datetime_end():
    result = inventory_service._date_to_datetime(
        date(2026, 8, 9),
        end_of_day=True,
    )

    assert result.hour == 23
    assert result.minute == 59

def test_aggregate_movement_rows():
    rows = [
        {
            "fecha": datetime(
                2026,
                8,
                1,
                tzinfo=timezone.utc,
            ),
            "tipo_movimiento": "entrada_compra",
            "cantidad": Decimal("10"),
            "stock_resultante": Decimal("10"),
        },
        {
            "fecha": datetime(
                2026,
                8,
                2,
                tzinfo=timezone.utc,
            ),
            "tipo_movimiento": "salida_venta",
            "cantidad": Decimal("3"),
            "stock_resultante": Decimal("7"),
        },
    ]

    result = inventory_service._aggregate_movement_rows(
        rows,
        window="month",
        include_previous=False,
    )

    assert len(result) == 1
    assert result[0]["inbound_quantity"] == Decimal("10")
    assert result[0]["outbound_quantity"] == Decimal("3")
    assert result[0]["net_quantity"] == Decimal("7")
    assert result[0]["movement_count"] == 2
    assert result[0]["ending_stock"] == Decimal("7")

def test_aggregate_movement_rows_previous_comparison():
    rows = [
        {
            "fecha": datetime(
                2026,
                7,
                1,
                tzinfo=timezone.utc,
            ),
            "tipo_movimiento": "entrada_compra",
            "cantidad": Decimal("10"),
            "stock_resultante": Decimal("10"),
        },
        {
            "fecha": datetime(
                2026,
                8,
                1,
                tzinfo=timezone.utc,
            ),
            "tipo_movimiento": "entrada_compra",
            "cantidad": Decimal("20"),
            "stock_resultante": Decimal("30"),
        },
    ]

    result = inventory_service._aggregate_movement_rows(
        rows,
        window="month",
        include_previous=True,
    )

    assert len(result) == 2
    assert result[0]["previous_net_quantity"] is None
    assert result[1]["previous_net_quantity"] == Decimal("10")
    assert result[1]["net_change_quantity"] == Decimal("10")
    assert result[1]["net_change_percent"] == Decimal("100.00")

def test_aggregate_previous_zero():
    rows = [
        {
            "fecha": datetime(
                2026,
                7,
                1,
                tzinfo=timezone.utc,
            ),
            "tipo_movimiento": "entrada_compra",
            "cantidad": Decimal("0"),
            "stock_resultante": Decimal("0"),
        },
        {
            "fecha": datetime(
                2026,
                8,
                1,
                tzinfo=timezone.utc,
            ),
            "tipo_movimiento": "entrada_compra",
            "cantidad": Decimal("5"),
            "stock_resultante": Decimal("5"),
        },
    ]

    result = inventory_service._aggregate_movement_rows(
        rows,
        window="month",
        include_previous=True,
    )

    assert result[1]["net_change_percent"] is None

def test_rank_product_rows_outbound():
    rows = [
        {
            "producto_id": "1",
            "sku": "A",
            "nombre": "A",
            "tipo_movimiento": "salida_venta",
            "cantidad": Decimal("20"),
            "stock_resultante": Decimal("5"),
            "stock_actual": Decimal("5"),
            "stock_minimo": Decimal("10"),
        },
        {
            "producto_id": "2",
            "sku": "B",
            "nombre": "B",
            "tipo_movimiento": "salida_venta",
            "cantidad": Decimal("5"),
            "stock_resultante": Decimal("20"),
            "stock_actual": Decimal("20"),
            "stock_minimo": Decimal("10"),
        },
    ]

    result = inventory_service._rank_product_rows(
        rows,
        sort_by="outbound",
        limit=10,
    )

    assert result[0]["sku"] == "A"

@pytest.mark.parametrize(
    "sort_by",
    [
        "outbound",
        "inbound",
        "net",
        "movement_count",
        "stock_risk",
    ],
)
def test_rank_product_rows_all_sort_modes(sort_by):
    rows = [
        {
            "producto_id": "1",
            "sku": "A",
            "nombre": "A",
            "tipo_movimiento": "entrada_compra",
            "cantidad": Decimal("10"),
            "stock_resultante": Decimal("2"),
            "stock_actual": Decimal("2"),
            "stock_minimo": Decimal("10"),
        }
    ]

    result = inventory_service._rank_product_rows(
        rows,
        sort_by=sort_by,
        limit=10,
    )

    assert len(result) == 1

def test_stock_risk_score_no_minimum():
    result = inventory_service._stock_risk_score(
        Decimal("5"),
        Decimal("0"),
        Decimal("10"),
    )

    assert result == Decimal("0")

def test_stock_risk_score_shortage():
    result = inventory_service._stock_risk_score(
        Decimal("2"),
        Decimal("10"),
        Decimal("20"),
    )

    assert result > Decimal("0")

def test_stock_risk_score_no_demand():
    result = inventory_service._stock_risk_score(
        Decimal("5"),
        Decimal("10"),
        Decimal("0"),
    )

    assert result > Decimal("0")

def test_empty_bucket():
    result = inventory_service._empty_bucket(
        date(2026, 8, 1),
        "month",
    )

    assert result["inbound_quantity"] == Decimal("0")
    assert result["outbound_quantity"] == Decimal("0")
    assert result["net_quantity"] == Decimal("0")
    assert result["movement_count"] == 0
    assert result["ending_stock"] is None

def test_get_monthly_behavior(inventory_db):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
    )

    _insert_movement(
        db,
        tables,
        product_id=product_id,
        movement_type="entrada_compra",
        quantity=Decimal("10"),
        stock_result=Decimal("20"),
    )

    result = inventory_service.get_monthly_behavior(
        user,
        db,
        period="30d",
    )

    assert "points" in result
    assert result["period"] == "30d"

def test_get_inventory_trend(inventory_db):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
    )

    _insert_movement(
        db,
        tables,
        product_id=product_id,
    )

    result = inventory_service.get_inventory_trend(
        user,
        db,
        period="30d",
        window="day",
    )

    assert result["window"] == "day"
    assert len(result["points"]) == 1

def test_get_product_analytics(inventory_db):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
    )

    _insert_movement(
        db,
        tables,
        product_id=product_id,
        movement_type="salida_venta",
        quantity=Decimal("4"),
        stock_result=Decimal("6"),
    )

    result = inventory_service.get_product_analytics(
        user,
        db,
        period="30d",
        sort_by="outbound",
        limit=10,
    )

    assert len(result["products"]) == 1
    assert result["products"][0]["outbound_quantity"] == Decimal("4")

def test_get_inventory_metrics(inventory_db):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
        stock=Decimal("3"),
        minimo=Decimal("5"),
    )

    _insert_movement(
        db,
        tables,
        product_id=product_id,
        movement_type="entrada_compra",
        quantity=Decimal("10"),
    )

    result = inventory_service.get_inventory_metrics(
        user,
        db,
        period="30d",
    )

    assert result["entradas"] == Decimal("10")
    assert result["stock_bajo"] == 1

def test_get_inventory_metrics_product_filter(inventory_db,):
    db, tables, user = inventory_db

    product_id = _insert_product(
        db,
        tables,
    )

    other = _insert_product(
        db,
        tables,
        sku="OTHER",
    )

    _insert_movement(
        db,
        tables,
        product_id=product_id,
        movement_type="entrada_compra",
        quantity=Decimal("10"),
    )

    _insert_movement(
        db,
        tables,
        product_id=other,
        movement_type="entrada_compra",
        quantity=Decimal("20"),
    )

    result = inventory_service.get_inventory_metrics(
        user,
        db,
        period="30d",
        product_id=product_id,
    )

    assert result["entradas"] == Decimal("10")

def test_to_decimal():
    assert inventory_service._to_decimal(
        Decimal("10")
    ) == Decimal("10")

    assert inventory_service._to_decimal(
        10
    ) == Decimal("10")

    assert inventory_service._to_decimal(
        "10.50"
    ) == Decimal("10.50")

def test_normalize_header():
    assert (
        inventory_service._normalize_header(
            "  SKU "
        )
        == "sku"
    )

def test_clean_text():
    assert inventory_service._clean_text("  hello ") == "hello"
    assert inventory_service._clean_text(None) == ""

def test_clean_optional_text():
    assert (
        inventory_service._clean_optional_text(
            "  hello "
        )
        == "hello"
    )

    assert (
        inventory_service._clean_optional_text(
            "   "
        )
        is None
    )

def test_parse_nonnegative_decimal_valid():
    errors = []

    result = inventory_service._parse_nonnegative_decimal(
        "12.50",
        "precio",
        2,
        errors,
    )

    assert result == Decimal("12.50")
    assert errors == []

def test_parse_nonnegative_decimal_empty():
    errors = []

    result = inventory_service._parse_nonnegative_decimal(
        "",
        "precio",
        2,
        errors,
    )

    assert result == Decimal("0")

def test_parse_nonnegative_decimal_invalid():
    errors = []

    result = inventory_service._parse_nonnegative_decimal(
        "abc",
        "precio",
        2,
        errors,
    )

    assert result == Decimal("0")
    assert errors[0]["code"] == "invalid_decimal"

def test_parse_nonnegative_decimal_negative():
    errors = []

    result = inventory_service._parse_nonnegative_decimal(
        "-10",
        "precio",
        2,
        errors,
    )

    assert result == Decimal("0")
    assert errors[0]["code"] == "negative_decimal"

def test_parse_optional_uuid_valid():
    errors = []
    value = uuid4()

    result = inventory_service._parse_optional_uuid(
        str(value),
        "proveedor_id",
        2,
        errors,
    )

    assert result == value
    assert errors == []

def test_parse_optional_uuid_empty():
    errors = []

    result = inventory_service._parse_optional_uuid(
        "",
        "proveedor_id",
        2,
        errors,
    )

    assert result is None

def test_parse_optional_uuid_invalid():
    errors = []

    result = inventory_service._parse_optional_uuid(
        "invalid",
        "proveedor_id",
        2,
        errors,
    )

    assert result is None
    assert errors[0]["code"] == "invalid_uuid"

def test_validate_csv_injection():
    errors = []

    inventory_service._validate_csv_injection(
        "=SUM(A1:A2)",
        2,
        "sku",
        errors,
    )

    assert errors[0]["code"] == "csv_injection"

def test_validate_csv_safe_value():
    errors = []

    inventory_service._validate_csv_injection(
        "SKU-123",
        2,
        "sku",
        errors,
    )

    assert errors == []

def _make_minimal_xlsx():
    workbook_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
              xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
        <sheets>
            <sheet name="Sheet1" sheetId="1" r:id="rId1"/>
        </sheets>
    </workbook>
    """

    workbook_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
        <Relationship
            Id="rId1"
            Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
            Target="worksheets/sheet1.xml"/>
    </Relationships>
    """

    sheet_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
        <sheetData>
            <row r="1">
                <c r="A1" t="inlineStr">
                    <is><t>sku</t></is>
                </c>
                <c r="B1" t="inlineStr">
                    <is><t>nombre</t></is>
                </c>
            </row>
            <row r="2">
                <c r="A2" t="inlineStr">
                    <is><t>SKU-XLSX</t></is>
                </c>
                <c r="B2" t="inlineStr">
                    <is><t>Producto XLSX</t></is>
                </c>
            </row>
        </sheetData>
    </worksheet>
    """

    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
        <Default Extension="rels"
            ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
        <Default Extension="xml"
            ContentType="application/xml"/>
        <Override PartName="/xl/workbook.xml"
            ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
        <Override PartName="/xl/worksheets/sheet1.xml"
            ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
    </Types>
    """

    root_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
        <Relationship
            Id="rId1"
            Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
            Target="xl/workbook.xml"/>
    </Relationships>
    """

    buffer = BytesIO()

    with zipfile.ZipFile(
        buffer,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr(
            "[Content_Types].xml",
            content_types,
        )
        archive.writestr(
            "_rels/.rels",
            root_rels,
        )
        archive.writestr(
            "xl/workbook.xml",
            workbook_xml,
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            workbook_rels,
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            sheet_xml,
        )

    return buffer.getvalue()

def test_parse_xlsx_valid():
    content = _make_minimal_xlsx()

    result = inventory_service.parse_product_import_file(
        "products.xlsx",
        content,
    )

    assert len(result) == 1
    assert result[0]["sku"] == "SKU-XLSX"
    assert result[0]["nombre"] == "Producto XLSX"

def test_read_xlsx_invalid_zip():
    with pytest.raises(ProductImportError) as exc:
        inventory_service.parse_product_import_file(
            "products.xlsx",
            b"not-an-xlsx",
        )

    assert exc.value.code == "invalid_format"

def test_read_xlsx_missing_sheet():
    buffer = BytesIO()

    with zipfile.ZipFile(
        buffer,
        "w",
        zipfile.ZIP_DEFLATED,
    ) as archive:
        archive.writestr(
            "xl/workbook.xml",
            "<workbook/>",
        )

    with pytest.raises(ProductImportError) as exc:
        inventory_service.parse_product_import_file(
            "products.xlsx",
            buffer.getvalue(),
        )

    assert exc.value.code == "invalid_format"