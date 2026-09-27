"""Upgrade existing tenants and purge expired history without invoking a model.

Run `python -m app.services.chat_maintenance --once` manually, or --watch hourly.
API startup upgrades existing tenants; tenant bootstrap handles new companies.
"""
import argparse
import logging
import time

from sqlalchemy import delete, select

from app.core.database import get_engine
from app.models.companies import Company
from app.models.tenant.registry import build_tenant_metadata
from app.services.chat_store import utcnow
from app.tenancy.bootstrap import validate_schema_name

logger = logging.getLogger(__name__)
CHAT_TABLES = ("chat_conversation", "chat_message")


def upgrade_chat_tables(connection, schema_name):
    validate_schema_name(schema_name)
    metadata = build_tenant_metadata(schema_name)
    metadata.create_all(connection, tables=[metadata.tables[f"{schema_name}.{name}"] for name in CHAT_TABLES])


def maintain_chat(engine, *, upgrade=False, now=None):
    now = now or utcnow()
    removed = 0
    with engine.connect() as connection:
        schemas = connection.execute(select(Company.schema_name)).scalars().all()
    # Include inactive companies: retention must continue after access is removed.
    for schema in schemas:
        validate_schema_name(schema)
        with engine.begin() as connection:
            if upgrade:
                upgrade_chat_tables(connection, schema)
            table = build_tenant_metadata(schema).tables[f"{schema}.chat_conversation"]
            removed += connection.execute(delete(table).where(table.c.expires_at <= now)).rowcount
    return removed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="store_true", help="Repeat cleanup hourly")
    parser.add_argument("--once", action="store_true", help="Run cleanup once (default)")
    parser.add_argument("--upgrade", action="store_true", help="Create missing chat tables before cleanup")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    engine = get_engine()
    while True:
        try:
            count = maintain_chat(engine, upgrade=args.upgrade)
            logger.info("Chat retention cleanup completed; removed %s conversations", count)
        except Exception:
            # No SQL parameters, conversation text or secrets in maintenance logs.
            logger.error("Chat retention cleanup failed; check database availability and schema upgrade")
            if not args.watch:
                raise SystemExit(1)
        if not args.watch:
            return
        time.sleep(3600)


if __name__ == "__main__":
    main()
