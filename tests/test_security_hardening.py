from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.tenant.registry import build_tenant_metadata
from app.schemas.commercial import ClientCreate, ClientUpdate
from app.services.commercial import create_client, update_client
from app.utils.exceptions import AppError


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_NAME = "tenant_" + "a" * 32


class Result:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None


class DB:
    def __init__(self, rows):
        self.rows = list(rows)
        self.commits = 0

    def execute(self, _statement):
        return Result(self.rows.pop(0) if self.rows else [])

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def user():
    return SimpleNamespace(
        company_id=uuid4(),
        company=SimpleNamespace(is_active=True, schema_name=SCHEMA_NAME),
    )


def test_client_table_has_case_insensitive_unique_indexes():
    metadata = build_tenant_metadata(SCHEMA_NAME)
    clients = metadata.tables[f"{SCHEMA_NAME}.cliente"]
    indexes = {index.name: index for index in clients.indexes}
    assert indexes["uq_cliente_nombre_ci"].unique is True
    assert indexes["uq_cliente_correo_ci"].unique is True


def test_the_unique_indexes_only_cover_active_clients():
    """A deactivated client keeps its history but must release its name."""
    metadata = build_tenant_metadata(SCHEMA_NAME)
    clients = metadata.tables[f"{SCHEMA_NAME}.cliente"]
    indexes = {index.name: index for index in clients.indexes}

    name_where = str(indexes["uq_cliente_nombre_ci"].dialect_options["postgresql"]["where"])
    email_where = str(indexes["uq_cliente_correo_ci"].dialect_options["postgresql"]["where"])

    assert name_where == "is_active"
    assert "is_active" in email_where
    assert "correo IS NOT NULL" in email_where


def test_create_rejects_client_name_with_different_case():
    db = DB([[{"id": uuid4(), "nombre": "ACME", "correo": None}]])
    with pytest.raises(AppError, match="Client name already exists"):
        create_client(ClientCreate(nombre="acme"), user(), db)
    assert db.commits == 0


def test_update_rejects_client_name_with_different_case():
    client_id = uuid4()
    db = DB(
        [
            [{"id": client_id}],
            [{"id": uuid4(), "nombre": "ACME", "correo": None}],
        ]
    )
    with pytest.raises(AppError, match="Client name already exists"):
        update_client(client_id, ClientUpdate(nombre="acme"), user(), db)
    assert db.commits == 0


def test_container_context_excludes_secrets_and_runtime_is_unprivileged():
    dockerignore = (ROOT / ".dockerignore").read_text()
    dockerfile = (ROOT / "Dockerfile").read_text()
    compose = (ROOT / "docker-compose.yml").read_text()
    assert ".env" in dockerignore
    assert "USER flowdesk" in dockerfile
    assert "cap_drop" in compose
    assert "no-new-privileges:true" in compose
    assert "Flowdesk2026!" not in compose
    assert "${DB_PASSWORD:?DB_PASSWORD is required}" in compose
