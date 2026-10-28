"""Startup gives existing tenants the partial unique indexes their tables predate."""
import logging
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from app.tenancy.bootstrap import _ensure_partial_unique_indexes
from app.tenancy.runtime import get_tenant_tables

SCHEMA = "tenant_" + "f" * 32
PARTIAL_INDEXES = {"uq_proveedor_nombre_ci", "uq_cliente_nombre_ci", "uq_cliente_correo_ci"}


class Result:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value

    def first(self):
        return self.value


class FakePostgres:
    """Answers the two lookups the migration makes and records every statement."""

    def __init__(self, definitions=None, duplicates=(), dialect="postgresql"):
        self.dialect = SimpleNamespace(name=dialect)
        self.definitions = definitions or {}
        self.duplicates = set(duplicates)
        self.statements = []

    def execute(self, statement, params=None):
        sql = str(statement.compile(dialect=postgresql.dialect()))
        self.statements.append(sql)
        if "FROM pg_indexes" in sql:
            return Result(self.definitions.get(params["name"]))
        if "HAVING count(*) > 1" in sql:
            table = sql.split(f'"{SCHEMA}".', 1)[1].split()[0].strip('"')
            return Result((1,) if table in self.duplicates else None)
        return Result(None)

    def ddl(self, verb):
        return [sql for sql in self.statements if sql.startswith(verb)]


def _run(connection):
    _ensure_partial_unique_indexes(connection, SCHEMA, list(get_tenant_tables(SCHEMA).values()))


def test_missing_indexes_are_created_with_their_condition():
    connection = FakePostgres()

    _run(connection)

    created = connection.ddl("CREATE UNIQUE INDEX")
    assert {sql.split()[3] for sql in created} == PARTIAL_INDEXES
    supplier = next(sql for sql in created if "uq_proveedor_nombre_ci" in sql)
    assert f"ON {SCHEMA}.proveedor (lower(nombre)) WHERE is_active" in supplier
    assert connection.ddl("DROP") == []


def test_indexes_already_in_their_declared_form_are_left_alone():
    connection = FakePostgres(definitions={
        "uq_proveedor_nombre_ci": f"CREATE UNIQUE INDEX uq_proveedor_nombre_ci ON {SCHEMA}.proveedor USING btree (lower((nombre)::text)) WHERE is_active",
        "uq_cliente_nombre_ci": f"CREATE UNIQUE INDEX uq_cliente_nombre_ci ON {SCHEMA}.cliente USING btree (lower((nombre)::text)) WHERE is_active",
        "uq_cliente_correo_ci": f"CREATE UNIQUE INDEX uq_cliente_correo_ci ON {SCHEMA}.cliente USING btree (lower((correo)::text)) WHERE ((correo IS NOT NULL) AND is_active)",
    })

    _run(connection)

    assert connection.ddl("CREATE") == []
    assert connection.ddl("DROP") == []


def test_indexes_from_before_the_active_condition_are_replaced():
    # The client indexes shipped on 2026-09-04 without is_active, which turned
    # reusing a deactivated client's name into a 500 on tenants made that day.
    connection = FakePostgres(definitions={
        "uq_cliente_nombre_ci": f"CREATE UNIQUE INDEX uq_cliente_nombre_ci ON {SCHEMA}.cliente USING btree (lower((nombre)::text))",
        "uq_cliente_correo_ci": f"CREATE UNIQUE INDEX uq_cliente_correo_ci ON {SCHEMA}.cliente USING btree (lower((correo)::text)) WHERE (correo IS NOT NULL)",
    })

    _run(connection)

    assert set(connection.ddl("DROP")) == {
        f'DROP INDEX "{SCHEMA}"."uq_cliente_nombre_ci"',
        f'DROP INDEX "{SCHEMA}"."uq_cliente_correo_ci"',
    }
    assert {sql.split()[3] for sql in connection.ddl("CREATE UNIQUE INDEX")} == PARTIAL_INDEXES


def test_tenant_with_duplicates_is_skipped_with_a_warning(caplog):
    connection = FakePostgres(duplicates={"proveedor"})

    with caplog.at_level(logging.WARNING):
        _run(connection)

    assert "uq_proveedor_nombre_ci" not in " ".join(connection.ddl("CREATE"))
    assert {sql.split()[3] for sql in connection.ddl("CREATE UNIQUE INDEX")} == {"uq_cliente_nombre_ci", "uq_cliente_correo_ci"}
    assert any("uq_proveedor_nombre_ci" in record.getMessage() for record in caplog.records)


def test_duplicate_check_groups_active_rows_by_the_index_expression():
    connection = FakePostgres()

    _run(connection)

    check = next(sql for sql in connection.statements if "HAVING" in sql and "proveedor" in sql)
    assert f'FROM "{SCHEMA}"."proveedor" WHERE is_active GROUP BY lower(nombre) HAVING count(*) > 1' in check


def test_other_databases_are_not_touched():
    connection = FakePostgres(dialect="sqlite")

    _run(connection)

    assert connection.statements == []
