from types import SimpleNamespace
from uuid import uuid4
import pytest
from app.schemas.commercial import ClientCreate, ClientUpdate
from app.services.commercial import create_client, delete_client, get_client, list_clients, update_client, update_client_status
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
    company = SimpleNamespace(
        is_active=True,
        schema_name=SCHEMA_NAME,
    )

    return SimpleNamespace(
        company_id=uuid4(),
        company=company,
    )

def make_client(
    is_active=True,
    nombre="Cliente Demo",
):
    return {
        "id": uuid4(),
        "nombre": nombre,
        "telefono": "5555-0101",
        "correo": "cliente@example.com",
        "direccion": "Zona 1",
        "is_active": is_active,
    }

def written_columns(statement):
    return {
        getattr(key, "name", key)
        for key in statement._values
    }

def test_create_client_rejects_duplicate_email():
    db = FakeDB([
        [{"id": uuid4()}],
    ])

    data = ClientCreate(
        nombre="Cliente",
        telefono=None,
        correo="cliente@example.com",
        direccion=None,
    )

    with pytest.raises(AppError) as error:
        create_client(
            data,
            make_user(),
            db,
        )

    assert error.value.status_code == 400
    assert error.value.detail == "Client email already exists"
    assert db.commits == 0

def test_create_client_persists_and_returns_client():
    created = make_client()

    db = FakeDB([
        [],
        [created],
    ])

    data = ClientCreate(
        nombre="  Cliente Demo  ",
        telefono="5555-0101",
        correo="CLIENTE@EXAMPLE.COM",
        direccion="Zona 1",
    )

    result = create_client(
        data,
        make_user(),
        db,
    )

    assert result == created
    assert db.commits == 1

    statement = db.statements[0]

    params = statement.compile().params

    assert params["nombre"] == "Cliente Demo"
    assert params["correo"] == "cliente@example.com"

def test_get_client_returns_client():
    client = make_client()

    db = FakeDB([
        [client],
    ])

    result = get_client(
        client["id"],
        make_user(),
        db,
    )

    assert result == client

def test_get_client_returns_404_when_not_found():
    db = FakeDB([
        [],
    ])

    with pytest.raises(AppError) as error:
        get_client(
            uuid4(),
            make_user(),
            db,
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Client not found"

def test_list_clients_returns_clients():
    clients = [
        make_client(),
        make_client(nombre="Otro Cliente"),
    ]

    db = FakeDB([
        clients,
    ])

    result = list_clients(
        make_user(),
        db,
    )

    assert result == clients

def test_list_clients_applies_search_filter():
    db = FakeDB([
        [make_client()],
    ])

    list_clients(
        make_user(),
        db,
        search="  cliente  ",
    )

    statement = db.statements[0]

    assert "%cliente%" in statement.compile().params.values()

def test_list_clients_can_include_inactive_clients():
    db = FakeDB([
        [make_client(is_active=False)],
    ])

    list_clients(
        make_user(),
        db,
        active_only=False,
    )

    statement = db.statements[0]

    assert "is_active" not in str(statement.whereclause)

def test_update_client_rejects_empty_payload():
    client = make_client()

    db = FakeDB([
        [client],
    ])

    with pytest.raises(AppError) as error:
        update_client(
            client["id"],
            ClientUpdate(),
            make_user(),
            db,
        )

    assert error.value.status_code == 400
    assert error.value.detail == "At least one field must be provided"
    assert db.commits == 0

def test_update_client_rejects_duplicate_email():
    client = make_client()

    db = FakeDB([
        [client],
        [{"id": uuid4()}],
    ])

    data = ClientUpdate(
        correo="other@example.com",
    )

    with pytest.raises(AppError) as error:
        update_client(
            client["id"],
            data,
            make_user(),
            db,
        )

    assert error.value.status_code == 400
    assert error.value.detail == "Client email already exists"
    assert db.commits == 0

def test_update_client_writes_only_sent_fields():
    client = make_client()

    db = FakeDB([
        [client],
        [client],
    ])

    update_client(
        client["id"],
        ClientUpdate(
            telefono="5555-0202",
        ),
        make_user(),
        db,
    )

    assert written_columns(db.statements[1]) == {
        "telefono",
        "updated_at",
    }

    assert db.commits == 1

def test_update_client_normalizes_email():
    client = make_client()

    db = FakeDB([
        [client],
        [],
        [client],
    ])

    update_client(
        client["id"],
        ClientUpdate(
            correo="  NEW@EXAMPLE.COM ",
        ),
        make_user(),
        db,
    )

    params = db.statements[1].compile().params

    assert params["correo"] == "new@example.com"

def test_update_client_status_rejects_nonexistent_client():
    db = FakeDB([
        [],
    ])

    with pytest.raises(AppError) as error:
        update_client_status(
            uuid4(),
            True,
            make_user(),
            db,
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Client not found"

def test_update_client_status_updates_status():
    client = make_client(is_active=True)

    db = FakeDB([
        [client],
        [client],
    ])

    result = update_client_status(
        client["id"],
        False,
        make_user(),
        db,
    )

    assert result == client
    assert db.commits == 1

    assert written_columns(db.statements[1]) == {
        "is_active",
        "updated_at",
    }

def test_delete_client_returns_404_when_not_found():
    db = FakeDB([
        [],
    ])

    with pytest.raises(AppError) as error:
        delete_client(
            uuid4(),
            make_user(),
            db,
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Client not found"

def test_delete_client_soft_deletes():
    client = make_client()

    db = FakeDB([
        [client],
    ])

    result = delete_client(
        client["id"],
        make_user(),
        db,
    )

    assert result is None
    assert db.commits == 1

    params = db.statements[1].compile().params

    assert params["is_active"] is False

def test_clients_reject_user_without_company():
    user = SimpleNamespace(
        company_id=None,
        company=None,
    )

    with pytest.raises(AppError) as error:
        list_clients(
            user,
            FakeDB(),
        )

    assert error.value.status_code == 403

def test_clients_reject_inactive_company():
    user = SimpleNamespace(
        company_id=uuid4(),
        company=SimpleNamespace(
            is_active=False,
            schema_name=SCHEMA_NAME,
        ),
    )

    with pytest.raises(AppError) as error:
        list_clients(
            user,
            FakeDB(),
        )

    assert error.value.status_code == 403

def test_clients_are_scoped_to_tenant_schema():
    db = FakeDB([
        [make_client()],
    ])

    list_clients(
        make_user(),
        db,
    )

    assert SCHEMA_NAME in str(db.statements[0])