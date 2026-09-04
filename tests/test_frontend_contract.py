from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.services.companies import list_companies
from app.utils.exceptions import AppError
from main import app


class Query:
    def __init__(self, rows):
        self.rows = rows

    def order_by(self, *_args):
        return self

    def all(self):
        return self.rows


class DB:
    def __init__(self, rows=None):
        self.rows = rows or []

    def query(self, _model):
        return Query(self.rows)


def user(role):
    return SimpleNamespace(id=uuid4(), role=SimpleNamespace(name=role))


def test_all_frontend_endpoints_are_registered():
    paths = {route.path for route in app.routes}
    expected = {
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/employees",
        "/api/v1/users",
        "/api/v1/roles",
        "/api/v1/companies",
        "/api/v1/inventory/products",
        "/api/v1/inventory/products/import",
        "/api/v1/inventory/movements",
        "/api/v1/inventory/metrics",
        "/api/v1/inventory/analytics/trend",
        "/api/v1/inventory/analytics/products",
        "/api/v1/tasks",
        "/health",
        "/ready",
    }
    assert expected <= paths


def test_company_listing_is_superadmin_only():
    company = SimpleNamespace(id=uuid4(), name="Acme")
    assert list_companies(DB([company]), user("superadmin")) == [company]
    with pytest.raises(AppError, match="Insufficient permissions"):
        list_companies(DB([company]), user("admin"))
