"""Fill an empty throwaway database with load test data for k6.

Creates the global tables and roles, N companies with their tenant schema, 8 users
per company sharing one known password, and about a year of business data. Writes a
fixture JSON with the logins and sample ids that tests/load/flowdesk_load.js reads.

Only for local throwaway databases: it refuses any host that is not local.

    python tests/load/seed_load_data.py \
        --dsn postgresql+psycopg2://postgres@127.0.0.1:55432/flowdesk_perf \
        --out /tmp/flowdesk_fixture.json
"""
import argparse
import json
import random
import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
DEFAULT_PASSWORD = "LoadTest-2026!"
DEFAULT_SIZES = {
    "suppliers": 50,
    "products": 1000,
    "clients": 300,
    "movements": 20000,
    "sales": 5000,
    "alerts": 100,
    "tasks_per_user": 20,
}
USERS_PER_COMPANY = (("admin", 1), ("manager", 2), ("employee", 5))
ENTRY_TYPES = ("entrada_compra", "entrada_manual", "ajuste_positivo", "devolucion_cliente")
EXIT_TYPES = ("salida_venta", "salida_manual", "ajuste_negativo", "devolucion_proveedor")
TASK_STATES = ("pendiente", "en_progreso", "completada", "cancelada")
TASK_PRIORITIES = ("baja", "media", "alta", "urgente")
TAX_RATE = Decimal("12.00")
CENT = Decimal("0.01")
FIXTURE_SAMPLE = 100


def require_local_dsn(dsn: str) -> str:
    host = urlsplit(dsn).hostname
    if host not in LOCAL_HOSTS:
        raise SystemExit(f"Refusing to seed a non local database host: {host!r}")
    return dsn


def _random_date(rng: random.Random, now: datetime, days: int = 365) -> datetime:
    return now - timedelta(seconds=rng.randint(0, days * 24 * 3600))


def build_tenant_rows(rng: random.Random, now: datetime, user_ids: list, sizes: dict) -> dict:
    """Rows for one tenant schema, keyed by table name. Pure, so it can be tested."""
    suppliers = [
        {
            "id": uuid4(),
            "nombre": f"Proveedor {n:03d}",
            "telefono": f"5550{n:04d}",
            "correo": f"proveedor{n}@load.example.com",
            "direccion": f"Zona {n % 20 + 1}",
        }
        for n in range(1, sizes["suppliers"] + 1)
    ]
    products = []
    for n in range(1, sizes["products"] + 1):
        products.append(
            {
                "id": uuid4(),
                "proveedor_id": rng.choice(suppliers)["id"],
                "sku": f"SKU-{n:05d}",
                "nombre": f"Producto {n:05d}",
                "descripcion": f"Producto de prueba {n}",
                "precio_venta": Decimal(rng.randint(100, 50000)) * CENT,
                "stock_actual": Decimal(rng.randint(0, 500)),
                "stock_minimo": Decimal(rng.randint(5, 50)),
            }
        )
    supplier_products = [
        {
            "id": uuid4(),
            "proveedor_id": supplier["id"],
            "producto_id": product["id"],
            "precio_cotizacion": (product["precio_venta"] * Decimal("0.7")).quantize(CENT),
        }
        for product in products
        for supplier in rng.sample(suppliers, 2)
    ]
    clients = [
        {
            "id": uuid4(),
            "nombre": f"Cliente {n:04d}",
            "telefono": f"4440{n:04d}",
            "correo": f"cliente{n}@load.example.com",
        }
        for n in range(1, sizes["clients"] + 1)
    ]

    movements = []
    for _ in range(sizes["movements"]):
        product = rng.choice(products)
        before = Decimal(rng.randint(0, 500))
        quantity = Decimal(rng.randint(1, 50))
        if before >= quantity and rng.random() < 0.5:
            kind, after = rng.choice(EXIT_TYPES), before - quantity
        else:
            kind, after = rng.choice(ENTRY_TYPES), before + quantity
        movements.append(
            {
                "id": uuid4(),
                "producto_id": product["id"],
                "usuario_id": rng.choice(user_ids),
                "tipo_movimiento": kind,
                "fecha": _random_date(rng, now),
                "cantidad": quantity,
                "stock_anterior": before,
                "stock_resultante": after,
                "motivo": "Carga de prueba",
            }
        )

    sales, sale_lines = [], []
    for _ in range(sizes["sales"]):
        sale_id = uuid4()
        subtotal = Decimal("0")
        for product in rng.sample(products, rng.randint(1, 5)):
            quantity = Decimal(rng.randint(1, 5))
            line_total = quantity * product["precio_venta"]
            subtotal += line_total
            sale_lines.append(
                {
                    "id": uuid4(),
                    "venta_id": sale_id,
                    "producto_id": product["id"],
                    "cantidad": quantity,
                    "precio_unitario": product["precio_venta"],
                    "subtotal": line_total,
                }
            )
        tax = (subtotal * TAX_RATE / 100).quantize(CENT)
        sales.append(
            {
                "id": sale_id,
                "usuario_id": rng.choice(user_ids),
                "cliente_id": rng.choice(clients)["id"] if rng.random() < 0.7 else None,
                "fecha": _random_date(rng, now),
                "subtotal": subtotal,
                "impuesto": tax,
                "tasa_impuesto": TAX_RATE,
                "total": subtotal + tax,
                "estado": "completada",
            }
        )

    alerts = [
        {
            "id": uuid4(),
            "producto_id": product["id"],
            "tipo": "stock_bajo",
            "mensaje": f"Stock bajo para {product['nombre']}",
            "fecha": _random_date(rng, now, days=30),
        }
        for product in rng.sample(products, sizes["alerts"])
    ]
    tasks = [
        {
            "id": uuid4(),
            "usuario_id": user_id,
            "titulo": f"Tarea {n}",
            "descripcion": "Tarea de prueba de carga",
            "fecha_limite": now + timedelta(days=rng.randint(1, 60)),
            "estado": rng.choice(TASK_STATES),
            "prioridad": rng.choice(TASK_PRIORITIES),
        }
        for user_id in user_ids
        for n in range(1, sizes["tasks_per_user"] + 1)
    ]

    return {
        "proveedor": suppliers,
        "producto": products,
        "proveedor_producto": supplier_products,
        "cliente": clients,
        "movimiento_inventario": movements,
        "venta": sales,
        "detalle_venta": sale_lines,
        "alerta": alerts,
        "tarea": tasks,
    }


def seed(dsn: str, out: Path, password: str, companies: int, scale: float) -> None:
    # App imports stay here so the pure helpers above can be tested without them.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from sqlalchemy import create_engine, insert, text
    from sqlalchemy.orm import Session

    from app.core.database import Base
    from app.core.security import hash_password
    from app.db.seeder import seed_roles
    from app.models.companies import Company
    from app.models.roles import Role
    from app.models.users import User
    from app.tenancy.bootstrap import bootstrap_tenant_schema, generate_schema_name
    from app.tenancy.runtime import get_tenant_tables

    sizes = {key: max(1, int(value * scale)) for key, value in DEFAULT_SIZES.items()}
    sizes["tasks_per_user"] = DEFAULT_SIZES["tasks_per_user"]
    rng = random.Random(2026)
    now = datetime.now().replace(microsecond=0)
    password_hash = hash_password(password)

    engine = create_engine(dsn)
    with engine.begin() as connection:
        connection.execute(text('CREATE SCHEMA IF NOT EXISTS "global"'))
    Base.metadata.create_all(bind=engine)

    fixture = {"password": password, "companies": []}
    with Session(engine) as db:
        seed_roles(db)
        if db.query(Company).filter(Company.name.like("Load Test %")).first():
            raise SystemExit("Load test companies already exist, start from an empty database")
        roles = {role.name: role.id for role in db.query(Role).all()}

        for number in range(1, companies + 1):
            company = Company(name=f"Load Test {number}", schema_name="")
            db.add(company)
            db.flush()
            company.schema_name = generate_schema_name(company.id)
            bootstrap_tenant_schema(db.connection(), company.schema_name)

            users = []
            for role, count in USERS_PER_COMPANY:
                for index in range(1, count + 1):
                    user = User(
                        username=f"load_c{number}_{role}{index}",
                        email=f"{role}{index}.c{number}@load.example.com",
                        password=password_hash,
                        role_id=roles[role],
                        company_id=company.id,
                        is_active=True,
                    )
                    db.add(user)
                    users.append(user)
            db.flush()

            rows = build_tenant_rows(rng, now, [user.id for user in users], sizes)
            tables = get_tenant_tables(company.schema_name)
            for table_name, table_rows in rows.items():
                db.execute(insert(tables[table_name]), table_rows)
            db.commit()

            fixture["companies"].append(
                {
                    "name": company.name,
                    "users": [{"email": user.email, "role": role_name(user, roles)} for user in users],
                    "product_ids": [str(row["id"]) for row in rows["producto"][:FIXTURE_SAMPLE]],
                    "supplier_ids": [str(row["id"]) for row in rows["proveedor"]],
                    "client_ids": [str(row["id"]) for row in rows["cliente"][:FIXTURE_SAMPLE]],
                    "sale_ids": [str(row["id"]) for row in rows["venta"][:FIXTURE_SAMPLE]],
                }
            )
            print(f"{company.name}: " + ", ".join(f"{name} {len(r)}" for name, r in rows.items()))

    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text("ANALYZE"))
    engine.dispose()
    out.write_text(json.dumps(fixture, indent=2))
    print(f"Fixture written to {out}")


def role_name(user, roles: dict) -> str:
    return next(name for name, role_id in roles.items() if role_id == user.role_id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dsn", required=True, help="SQLAlchemy URL of an empty local database")
    parser.add_argument("--out", required=True, type=Path, help="Where to write the k6 fixture JSON")
    parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Password for every seeded user")
    parser.add_argument("--companies", type=int, default=2)
    parser.add_argument("--scale", type=float, default=1.0, help="Multiplier for the data volume")
    args = parser.parse_args()
    seed(require_local_dsn(args.dsn), args.out, args.password, args.companies, args.scale)


if __name__ == "__main__":
    main()
