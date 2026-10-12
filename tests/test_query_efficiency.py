"""Query count and per-row work of the endpoints the load test found expensive.

Each case runs against an in-memory SQLite engine and counts the SELECT statements
that reach it, so the numbers are the round trips the code really makes.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import Column, MetaData, Table, Uuid, create_engine, event, insert
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.dependencies.auth import get_current_user
from app.core.database import Base
from app.core.security import create_access_token
from app.models.companies import Company
from app.models.roles import Role
from app.models.users import User
from app.schemas.commercial import ClientCreate, ClientResponse
from app.services import commercial as commercial_service
from app.services import inventory as inventory_service
from app.tenancy.runtime import get_tenant_tables


def sqlite_engine():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def attach_global(connection, _record):
        connection.execute("ATTACH DATABASE ':memory:' AS global")

    return engine


def count_selects(engine):
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def record(_conn, _cursor, statement, *_args):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    return statements


# --- authentication -----------------------------------------------------------


@pytest.fixture
def auth_db():
    engine = sqlite_engine()
    Base.metadata.create_all(engine, tables=[Role.__table__, Company.__table__, User.__table__])
    with Session(engine) as db:
        role = Role(name="manager", description="", created_at=datetime(2026, 1, 1))
        company = Company(name="Acme", schema_name="tenant_" + "a" * 32, is_active=True, created_at=datetime(2026, 1, 1))
        db.add_all([role, company])
        db.flush()
        user = User(
            username="manager",
            email="manager@example.com",
            password="x",
            role_id=role.id,
            company_id=company.id,
            is_active=True,
            created_at=datetime(2026, 1, 1),
        )
        db.add(user)
        db.commit()
        user_id = user.id
    with Session(engine) as db:
        yield engine, db, user_id


def test_current_user_loads_company_and_role_in_one_query(auth_db):
    engine, db, user_id = auth_db
    token = create_access_token({"sub": str(user_id)})
    selects = count_selects(engine)

    user = get_current_user(token=token, db=db)

    assert (user.company.schema_name, user.role.name) == ("tenant_" + "a" * 32, "manager")
    assert len(selects) == 1


# --- client listing -----------------------------------------------------------


def client_row(**overrides):
    row = {
        "id": uuid4(),
        "nombre": "Cliente",
        "telefono": None,
        "correo": "cliente@example.com",
        "direccion": None,
        "is_active": True,
        "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 1),
    }
    return {**row, **overrides}


def test_client_response_keeps_email_normalization():
    response = ClientResponse.model_validate(client_row(correo="  Mixed.Case@Example.COM "))

    assert response.correo == "mixed.case@example.com"


def test_client_response_does_not_revalidate_stored_emails(monkeypatch):
    import email_validator

    def fail(*_args, **_kwargs):
        raise AssertionError("stored emails were validated again on output")

    monkeypatch.setattr(email_validator, "validate_email", fail)

    assert ClientResponse.model_validate(client_row()).correo == "cliente@example.com"


def test_client_input_still_validates_email():
    with pytest.raises(ValidationError):
        ClientCreate(nombre="Cliente", correo="not-an-email")


# --- inventory analytics ------------------------------------------------------


def movement_rows(count, start=datetime(2026, 1, 1)):
    return [
        {
            "producto_id": UUID(int=index % 3 + 1),
            "tipo_movimiento": "entrada_manual" if index % 2 else "salida_manual",
            "fecha": start + timedelta(days=index % 50),
            "cantidad": Decimal("2"),
            "stock_resultante": Decimal(index),
            "sku": f"SKU-{index % 3}",
            "nombre": f"Producto {index % 3}",
            "stock_actual": Decimal("10"),
            "stock_minimo": Decimal("5"),
        }
        for index in range(count)
    ]


def test_aggregation_builds_each_bucket_once(monkeypatch):
    created = []
    original = inventory_service._empty_bucket

    def counting(bucket_start, window):
        created.append(bucket_start)
        return original(bucket_start, window)

    monkeypatch.setattr(inventory_service, "_empty_bucket", counting)

    points = inventory_service._aggregate_movement_rows(movement_rows(600), window="month", include_previous=True)

    assert len(points) == 2
    assert len(created) == 2
