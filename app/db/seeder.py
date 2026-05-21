from decimal import Decimal
from uuid import uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.orm import Session

from app.models.companies import Company
from app.models.roles import Role
from app.models.users import User
from app.core.security import hash_password
from app.core.config import DEMO_USER_PASSWORD, SUPERADMIN_EMAIL, SUPERADMIN_USERNAME, SUPERADMIN_PASSWORD
from app.tenancy.bootstrap import bootstrap_tenant_schema, generate_schema_name
from app.tenancy.runtime import get_tenant_tables

DEFAULT_ROLES = [
    {"name": "superadmin", "description": "Full access to all resources and settings."},
    {"name": "admin", "description": "Manage inventory, sales, and users within their company."},
    {"name": "manager", "description": "Manage inventory and sales, but cannot manage users."},
    {"name": "employee", "description": "View inventory and sales, but cannot make changes."},
]

def seed_roles(db: Session):
    for role_data in DEFAULT_ROLES:
        exists = db.query(Role).filter(Role.name == role_data["name"]).first()
        if not exists:
            db.add(Role(**role_data))
    db.commit()

def seed_superadmin(db: Session):
    exists = db.query(User).filter(User.email == SUPERADMIN_EMAIL).first()
    if exists:
        return

    superadmin_role = db.query(Role).filter(Role.name == "superadmin").first()
    if not superadmin_role:
        raise Exception("Superadmin role not found — run seed_roles first")

    superadmin = User(
        username=SUPERADMIN_USERNAME,
        email=SUPERADMIN_EMAIL,
        password=hash_password(SUPERADMIN_PASSWORD),
        role_id=superadmin_role.id,
        company_id=None,  # superadmin belongs to no company
        is_active=True,
    )
    db.add(superadmin)
    db.commit()


def seed_demo_data(db: Session):
    roles = {role.name: role for role in db.query(Role).all()}
    required_roles = {"admin", "manager", "employee"}
    missing_roles = required_roles - set(roles)
    if missing_roles:
        raise Exception(f"Missing demo roles: {', '.join(sorted(missing_roles))}")

    company = db.query(Company).filter(Company.name == "Flowdesk Demo").first()
    if not company:
        company = Company(name="Flowdesk Demo", schema_name="")
        db.add(company)
        db.flush()
        company.schema_name = generate_schema_name(company.id)

    bootstrap_tenant_schema(db.connection(), company.schema_name)
    _seed_demo_users(db, company, roles)
    _seed_demo_inventory(db, company)
    db.commit()


def _seed_demo_users(db: Session, company: Company, roles: dict[str, Role]) -> None:
    users = [
        ("demo_admin", "admin.demo@flowdesk.local", roles["admin"].id),
        ("demo_manager", "manager.demo@flowdesk.local", roles["manager"].id),
        ("demo_employee", "employee.demo@flowdesk.local", roles["employee"].id),
    ]
    for username, email, role_id in users:
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            continue
        db.add(
            User(
                username=username,
                email=email,
                password=hash_password(DEMO_USER_PASSWORD),
                role_id=role_id,
                company_id=company.id,
                is_active=True,
            )
        )


def _seed_demo_inventory(db: Session, company: Company) -> None:
    tables = get_tenant_tables(company.schema_name)
    suppliers = tables["proveedor"]
    products = tables["producto"]
    movements = tables["movimiento_inventario"]
    alerts = tables["alerta"]

    supplier_id = _ensure_demo_supplier(db, suppliers)
    product_ids = _ensure_demo_products(db, products, supplier_id)
    _ensure_demo_movements(db, products, movements, product_ids)
    _ensure_demo_alerts(db, alerts, product_ids)


def _ensure_demo_supplier(db: Session, suppliers):
    existing = db.execute(
        select(suppliers.c.id).where(suppliers.c.nombre == "Proveedor Demo")
    ).mappings().first()
    if existing:
        return existing["id"]
    supplier_id = uuid4()
    db.execute(
        insert(suppliers).values(
            id=supplier_id,
            nombre="Proveedor Demo",
            telefono="5555-0101",
            correo="proveedor.demo@flowdesk.local",
            direccion="Ciudad de Guatemala",
        )
    )
    return supplier_id


def _ensure_demo_products(db: Session, products, supplier_id):
    demo_products = [
        {
            "sku": "DEMO-ARROZ",
            "nombre": "Arroz demo",
            "precio_venta": Decimal("18.50"),
            "stock_actual": Decimal("28"),
            "stock_minimo": Decimal("10"),
        },
        {
            "sku": "DEMO-FRIJOL",
            "nombre": "Frijol demo",
            "precio_venta": Decimal("22.00"),
            "stock_actual": Decimal("4"),
            "stock_minimo": Decimal("8"),
        },
        {
            "sku": "DEMO-CAFE",
            "nombre": "Cafe demo",
            "precio_venta": Decimal("45.00"),
            "stock_actual": Decimal("0"),
            "stock_minimo": Decimal("5"),
        },
    ]
    product_ids = {}
    for data in demo_products:
        existing = db.execute(
            select(products.c.id).where(products.c.sku == data["sku"])
        ).mappings().first()
        if existing:
            product_ids[data["sku"]] = existing["id"]
            continue
        product_id = uuid4()
        product_ids[data["sku"]] = product_id
        db.execute(
            insert(products).values(
                id=product_id,
                proveedor_id=supplier_id,
                sku=data["sku"],
                nombre=data["nombre"],
                descripcion="Producto de demostracion",
                precio_venta=data["precio_venta"],
                stock_actual=data["stock_actual"],
                stock_minimo=data["stock_minimo"],
                unidad_medida="unidad",
            )
        )
    return product_ids


def _ensure_demo_movements(db: Session, products, movements, product_ids: dict[str, object]) -> None:
    existing = db.execute(
        select(movements.c.id).where(movements.c.referencia_tipo == "demo_seed")
    ).first()
    if existing:
        return

    movement_rows = [
        ("DEMO-ARROZ", "entrada_compra", Decimal("35"), Decimal("0"), Decimal("35"), "Ingreso inicial demo"),
        ("DEMO-ARROZ", "salida_venta", Decimal("7"), Decimal("35"), Decimal("28"), "Venta demo"),
        ("DEMO-FRIJOL", "entrada_compra", Decimal("10"), Decimal("0"), Decimal("10"), "Ingreso inicial demo"),
        ("DEMO-FRIJOL", "salida_venta", Decimal("6"), Decimal("10"), Decimal("4"), "Venta demo"),
        ("DEMO-CAFE", "entrada_compra", Decimal("5"), Decimal("0"), Decimal("5"), "Ingreso inicial demo"),
        ("DEMO-CAFE", "salida_venta", Decimal("5"), Decimal("5"), Decimal("0"), "Venta demo"),
    ]
    for sku, movement_type, quantity, previous_stock, resulting_stock, reason in movement_rows:
        product_id = product_ids[sku]
        db.execute(
            insert(movements).values(
                id=uuid4(),
                producto_id=product_id,
                usuario_id=None,
                tipo_movimiento=movement_type,
                cantidad=quantity,
                stock_anterior=previous_stock,
                stock_resultante=resulting_stock,
                motivo=reason,
                referencia_tipo="demo_seed",
                referencia_id=None,
            )
        )
        db.execute(
            update(products).where(products.c.id == product_id).values(stock_actual=resulting_stock)
        )


def _ensure_demo_alerts(db: Session, alerts, product_ids: dict[str, object]) -> None:
    alert_rows = [
        ("DEMO-FRIJOL", "stock_bajo", "El producto 'Frijol demo' alcanzo stock bajo (4 <= 8)."),
        ("DEMO-CAFE", "sin_stock", "El producto 'Cafe demo' no tiene stock disponible."),
    ]
    for sku, alert_type, message in alert_rows:
        product_id = product_ids[sku]
        existing = db.execute(
            select(alerts.c.id).where(
                alerts.c.producto_id == product_id,
                alerts.c.tipo == alert_type,
                alerts.c.estado == "pendiente",
            )
        ).first()
        if existing:
            continue
        db.execute(
            insert(alerts).values(
                id=uuid4(),
                producto_id=product_id,
                tipo=alert_type,
                mensaje=message,
                estado="pendiente",
            )
        )
