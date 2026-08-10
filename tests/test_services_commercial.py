from uuid import uuid4
import pytest
from sqlalchemy import Boolean, DateTime, MetaData, Numeric, String, Table, create_engine, insert, select
from sqlalchemy.orm import Session, sessionmaker
from app.schemas.commercial import ClientCreate, ClientUpdate
from app.services import commercial as commercial_service
from app.utils.exceptions import AppError

@pytest.fixture
def commercial_db(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
    )

    metadata = MetaData()

    clients = Table(
        "cliente",
        metadata,
        __import__("sqlalchemy").Column(
            "id",
            String(36),
            primary_key=True,
        ),
        __import__("sqlalchemy").Column(
            "nombre",
            String(150),
            nullable=False,
        ),
        __import__("sqlalchemy").Column(
            "telefono",
            String(50),
            nullable=True,
        ),
        __import__("sqlalchemy").Column(
            "correo",
            String(150),
            nullable=True,
        ),
        __import__("sqlalchemy").Column(
            "direccion",
            String(250),
            nullable=True,
        ),
        __import__("sqlalchemy").Column(
            "is_active",
            Boolean,
            nullable=False,
            default=True,
        ),
        __import__("sqlalchemy").Column(
            "created_at",
            DateTime,
            nullable=True,
        ),
        __import__("sqlalchemy").Column(
            "updated_at",
            DateTime,
            nullable=True,
        ),
    )

    metadata.create_all(engine)

    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        expire_on_commit=False,
    )

    db = SessionLocal()
    current_user = object()

    monkeypatch.setattr(
        commercial_service,
        "_clients_table",
        lambda _current_user: clients,
    )

    yield db, clients, current_user

    db.close()
    engine.dispose()

def _insert_client(
    db,
    *,
    client_id=None,
    nombre="Cliente Demo",
    telefono="55555555",
    correo="cliente@test.com",
    direccion="Guatemala",
    is_active=True,
):
    client_id = client_id or uuid4()

    db.execute(
        insert(
            commercial_service._clients_table(None)
        ).values(
            id=str(client_id),
            nombre=nombre,
            telefono=telefono,
            correo=correo,
            direccion=direccion,
            is_active=is_active,
        )
    )
    db.commit()

    return client_id

def _row(db, clients, client_id):
    return db.execute(
        select(clients).where(clients.c.id == str(client_id))
    ).mappings().first()

def test_list_clients_returns_active_clients(commercial_db):
    db, clients, user = commercial_db

    _insert_client(
        db,
        nombre="Cliente Activo",
        correo="activo@test.com",
        is_active=True,
    )
    _insert_client(
        db,
        nombre="Cliente Inactivo",
        correo="inactivo@test.com",
        is_active=False,
    )

    result = commercial_service.list_clients(
        user,
        db,
    )

    assert len(result) == 1
    assert result[0]["nombre"] == "Cliente Activo"

def test_list_clients_includes_inactive_when_requested(commercial_db):
    db, clients, user = commercial_db

    _insert_client(
        db,
        nombre="Activo",
        is_active=True,
    )
    _insert_client(
        db,
        nombre="Inactivo",
        correo="inactive@test.com",
        is_active=False,
    )

    result = commercial_service.list_clients(
        user,
        db,
        active_only=False,
    )

    assert len(result) == 2

@pytest.mark.parametrize("search_field", ["nombre", "correo", "telefono"],)
def test_list_clients_searches_multiple_fields(commercial_db, search_field,):
    db, clients, user = commercial_db

    values = {
        "nombre": "Empresa Especial",
        "correo": "especial@test.com",
        "telefono": "77777777",
    }

    _insert_client(
        db,
        nombre=values["nombre"],
        correo=values["correo"],
        telefono=values["telefono"],
    )

    result = commercial_service.list_clients(
        user,
        db,
        search="  ESPECIAL  " if search_field != "telefono" else "777777",
    )

    assert len(result) == 1

def test_list_clients_search_no_results(commercial_db):
    db, clients, user = commercial_db

    _insert_client(db)

    result = commercial_service.list_clients(
        user,
        db,
        search="does-not-exist",
    )

    assert result == []

def test_get_client(commercial_db):
    db, clients, user = commercial_db
    client_id = _insert_client(db)

    result = commercial_service.get_client(
        client_id,
        user,
        db,
    )

    assert result["id"] == str(client_id)
    assert result["nombre"] == "Cliente Demo"

def test_get_client_not_found(commercial_db):
    db, clients, user = commercial_db

    with pytest.raises(AppError) as exc:
        commercial_service.get_client(
            uuid4(),
            user,
            db,
        )

    assert exc.value.status_code == 404

def test_create_client_normalizes_values(commercial_db):
    db, clients, user = commercial_db

    data = ClientCreate(
        nombre="  Nuevo Cliente  ",
        telefono=" 5551234 ",
        correo=" CLIENTE@TEST.COM ",
        direccion=" Guatemala ",
    )

    result = commercial_service.create_client(
        data,
        user,
        db,
    )

    assert result["nombre"] == "Nuevo Cliente"
    assert result["telefono"] == "5551234"
    assert result["correo"] == "cliente@test.com"
    assert result["direccion"] == "Guatemala"

def test_create_client_without_optional_values(commercial_db):
    db, clients, user = commercial_db

    data = ClientCreate(
        nombre="Cliente Sin Datos",
    )

    result = commercial_service.create_client(
        data,
        user,
        db,
    )

    assert result["nombre"] == "Cliente Sin Datos"

def test_create_client_duplicate_email(commercial_db):
    db, clients, user = commercial_db

    _insert_client(
        db,
        correo="duplicate@test.com",
    )

    data = ClientCreate(
        nombre="Otro",
        correo=" DUPLICATE@TEST.COM ",
    )

    with pytest.raises(AppError) as exc:
        commercial_service.create_client(
            data,
            user,
            db,
        )

    assert exc.value.status_code == 400
    assert "email" in exc.value.message.lower()

def test_update_client(commercial_db):
    db, clients, user = commercial_db
    client_id = _insert_client(db)

    data = ClientUpdate(
        nombre="Cliente Modificado",
        telefono="99999999",
    )

    result = commercial_service.update_client(
        client_id,
        data,
        user,
        db,
    )

    assert result["nombre"] == "Cliente Modificado"
    assert result["telefono"] == "99999999"

def test_update_client_only_email(commercial_db):
    db, clients, user = commercial_db
    client_id = _insert_client(db)

    data = ClientUpdate(
        correo=" NEW@EMAIL.COM ",
    )

    result = commercial_service.update_client(
        client_id,
        data,
        user,
        db,
    )

    assert result["correo"] == "new@email.com"

def test_update_client_not_found(commercial_db):
    db, clients, user = commercial_db

    with pytest.raises(AppError) as exc:
        commercial_service.update_client(
            uuid4(),
            ClientUpdate(nombre="Nuevo"),
            user,
            db,
        )

    assert exc.value.status_code == 404

def test_update_client_without_fields(commercial_db):
    db, clients, user = commercial_db
    client_id = _insert_client(db)

    with pytest.raises(AppError) as exc:
        commercial_service.update_client(
            client_id,
            ClientUpdate(),
            user,
            db,
        )

    assert exc.value.status_code == 400

def test_update_client_duplicate_email(commercial_db):
    db, clients, user = commercial_db
    first = _insert_client(db, correo="first@test.com",)

    _insert_client(
        db,
        nombre="Second",
        correo="second@test.com",
    )

    with pytest.raises(AppError) as exc:
        commercial_service.update_client(
            first,
            ClientUpdate(correo="SECOND@TEST.COM"),
            user,
            db,
        )

    assert exc.value.status_code == 400

def test_update_client_all_supported_fields(commercial_db):
    db, clients, user = commercial_db
    client_id = _insert_client(db)

    result = commercial_service.update_client(
        client_id,
        ClientUpdate(
            nombre=" Nombre ",
            telefono=" Tel ",
            correo=" MAIL@TEST.COM ",
            direccion=" Dirección ",
        ),
        user,
        db,
    )

    assert result["nombre"] == "Nombre"
    assert result["telefono"] == "Tel"
    assert result["correo"] == "mail@test.com"
    assert result["direccion"] == "Dirección"

def test_update_client_status(commercial_db):
    db, clients, user = commercial_db
    client_id = _insert_client(db)

    result = commercial_service.update_client_status(
        client_id,
        False,
        user,
        db,
    )

    assert result["is_active"] is False

def test_update_client_status_same_status(commercial_db):
    db, clients, user = commercial_db

    client_id = _insert_client(
        db,
        is_active=True,
    )

    with pytest.raises(AppError) as exc:
        commercial_service.update_client_status(
            client_id,
            True,
            user,
            db,
        )

    assert exc.value.status_code == 400

def test_update_client_status_not_found(commercial_db):
    db, clients, user = commercial_db

    with pytest.raises(AppError) as exc:
        commercial_service.update_client_status(
            uuid4(),
            True,
            user,
            db,
        )

    assert exc.value.status_code == 404

def test_delete_client_soft_deletes(commercial_db):
    db, clients, user = commercial_db
    client_id = _insert_client(db)

    result = commercial_service.delete_client(
        client_id,
        user,
        db,
    )

    assert result is None

    row = _row(
        db,
        clients,
        client_id,
    )

    assert row["is_active"] is False

def test_delete_client_not_found(commercial_db):
    db, clients, user = commercial_db

    with pytest.raises(AppError) as exc:
        commercial_service.delete_client(
            uuid4(),
            user,
            db,
        )

    assert exc.value.status_code == 404

def test_client_payload_normalizes_every_field(commercial_db):
    db, clients, user = commercial_db

    payload = commercial_service._client_payload(
        ClientCreate(
            nombre="  Nombre ",
            telefono=" 123 ",
            correo=" TEST@TEST.COM ",
            direccion=" Calle ",
        )
    )

    assert payload == {
        "nombre": "Nombre",
        "telefono": "123",
        "correo": "test@test.com",
        "direccion": "Calle",
    }

def test_client_payload_exclude_unset(commercial_db):
    db, clients, user = commercial_db

    payload = commercial_service._client_payload(
        ClientUpdate(nombre=" Nuevo "),
        exclude_unset=True,
    )

    assert payload == {
        "nombre": "Nuevo",
    }

def test_client_payload_excludes_none(commercial_db):
    db, clients, user = commercial_db

    payload = commercial_service._client_payload(
        ClientUpdate(
            nombre="Nuevo",
            correo=None,
        ),
        exclude_unset=True,
    )

    assert "correo" not in payload

def test_ensure_email_available_allows_same_client(commercial_db):
    db, clients, user = commercial_db

    client_id = _insert_client(
        db,
        correo="same@test.com",
    )

    commercial_service._ensure_email_available(
        db,
        clients,
        "same@test.com",
        exclude_client_id=client_id,
    )

def test_ensure_email_available_empty_email(commercial_db):
    db, clients, user = commercial_db

    commercial_service._ensure_email_available(
        db,
        clients,
        None,
    )

def test_ensure_client_exists_success(commercial_db):
    db, clients, user = commercial_db
    client_id = _insert_client(db)

    commercial_service._ensure_client_exists(
        db,
        clients,
        client_id,
    )

def test_ensure_client_exists_failure(commercial_db):
    db, clients, user = commercial_db

    with pytest.raises(AppError) as exc:
        commercial_service._ensure_client_exists(
            db,
            clients,
            uuid4(),
        )

    assert exc.value.status_code == 404