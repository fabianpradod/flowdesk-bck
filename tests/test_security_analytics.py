"""Metrics and analytics respect authentication, company and permissions.

Scope: the inventory analytics (/inventory/analytics/*, /metrics, /history), the
sales and catalog analytics (/analytics/*) and the reports, which all share one
date range resolver. Authentication and the
manager floor are covered route by route in test_security_authentication and
test_security_roles; this file checks what is particular to aggregates: that an
aggregate built for one company can never fold in another company's rows, and
that the date inputs cannot crash the endpoint.
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from tests.security_helpers import (
    FakeQuery,
    FakeResult,
    client_for,
    make_company,
    make_user,
    schemas_in,
)

ANALYTICS = (
    "/api/v1/inventory/analytics/monthly",
    "/api/v1/inventory/analytics/trend",
    "/api/v1/inventory/analytics/products",
    "/api/v1/inventory/metrics",
    "/api/v1/inventory/history",
)

RANGED = (
    "/api/v1/inventory/analytics/monthly",
    "/api/v1/inventory/analytics/trend",
    "/api/v1/inventory/analytics/products",
    "/api/v1/inventory/metrics",
    "/api/v1/reports/movimientos",
    "/api/v1/reports/alertas",
    "/api/v1/analytics/sales/metrics",
    "/api/v1/analytics/sales/trend",
    "/api/v1/analytics/sales/top-products",
    "/api/v1/analytics/inventory/risk-distribution",
    "/api/v1/analytics/catalog/product-creation-trend",
)


def _movement_row(sku, quantity):
    """One row carrying every column the analytics queries select."""
    return {
        "id": uuid4(),
        "producto_id": uuid4(),
        "sku": sku,
        "nombre": sku.upper(),
        "tipo_movimiento": "entrada_manual",
        "fecha": datetime.now(timezone.utc),
        "cantidad": Decimal(quantity),
        "stock_resultante": Decimal(quantity),
        "motivo": None,
        "stock_actual": Decimal(quantity),
        "stock_minimo": Decimal("0"),
        "is_active": True,
    }


class TwoTenantDB:
    """Holds rows for two companies and answers each statement with the rows of
    the schema it names. If a query ever named both schemas, or the wrong one, the
    other company's quantities would show up in the aggregate."""

    def __init__(self, rows_by_schema):
        self.rows_by_schema = rows_by_schema
        self.statements = []

    def execute(self, statement, *_args, **_kwargs):
        self.statements.append(statement)
        rows = []
        for schema in schemas_in([statement]):
            rows.extend(self.rows_by_schema.get(schema, []))
        return FakeResult(rows)

    def query(self, _model):
        return FakeQuery()

    def commit(self):
        pass

    def rollback(self):
        pass


@pytest.fixture
def two_companies():
    company_a, company_b = make_company(name="A"), make_company(name="B")
    db = TwoTenantDB({
        company_a.schema_name: [_movement_row("sku-a", "5")],
        company_b.schema_name: [_movement_row("sku-b", "1000")],
    })
    return company_a, company_b, db


def _get(company, db, path, **params):
    return client_for(make_user("manager", company), db).get(path, params=params)


@pytest.mark.parametrize("path", ANALYTICS)
def test_analytics_only_read_the_callers_schema(two_companies, path):
    company_a, _company_b, db = two_companies

    response = _get(company_a, db, path)

    assert response.status_code == 200
    assert schemas_in(db.statements) == {company_a.schema_name}


def test_metrics_only_add_up_the_callers_movements(two_companies):
    company_a, company_b, db = two_companies

    mine = _get(company_a, db, "/api/v1/inventory/metrics").json()
    theirs = _get(company_b, db, "/api/v1/inventory/metrics").json()

    assert Decimal(mine["entradas"]) == Decimal("5")
    assert Decimal(theirs["entradas"]) == Decimal("1000")


@pytest.mark.parametrize("path", [
    "/api/v1/inventory/analytics/monthly",
    "/api/v1/inventory/analytics/trend",
])
def test_trends_only_add_up_the_callers_movements(two_companies, path):
    company_a, _company_b, db = two_companies

    points = _get(company_a, db, path).json()["points"]

    assert sum(Decimal(point["inbound_quantity"]) for point in points) == Decimal("5")


def test_product_ranking_only_lists_the_callers_products(two_companies):
    company_a, _company_b, db = two_companies

    products = _get(company_a, db, "/api/v1/inventory/analytics/products").json()["products"]

    assert [product["sku"] for product in products] == ["sku-a"]


def test_history_only_lists_the_callers_movements(two_companies):
    company_a, _company_b, db = two_companies

    rows = _get(company_a, db, "/api/v1/inventory/history").json()

    assert [row["sku"] for row in rows] == ["sku-a"]


@pytest.mark.parametrize("path", ANALYTICS)
def test_another_companys_product_filter_yields_no_foreign_data(two_companies, path):
    """The product filter narrows the caller's own schema; it cannot point elsewhere."""
    company_a, company_b, db = two_companies
    foreign_product = db.rows_by_schema[company_b.schema_name][0]["producto_id"]

    response = _get(company_a, db, path, product_id=str(foreign_product))

    assert response.status_code == 200
    assert "sku-b" not in response.text
    assert "1000" not in response.text
    assert schemas_in(db.statements) == {company_a.schema_name}


# Date inputs

@pytest.mark.parametrize("path", RANGED)
@pytest.mark.parametrize("params", [
    {"period": "7d", "end_date": "0001-01-02"},
    {"period": "12m", "end_date": "0001-06-01"},
])
def test_a_range_before_the_calendar_start_is_a_bad_request(path, params):
    """The start is computed as end minus the period; near year 1 that overflowed
    and answered 500."""
    response = client_for(make_user("admin", make_company())).get(path, params=params)

    assert response.status_code == 400, response.text
    assert response.json()["code"] == "app_error"


@pytest.mark.parametrize("path", RANGED)
def test_a_reversed_custom_range_is_a_bad_request(path):
    response = client_for(make_user("admin", make_company())).get(
        path, params={"period": "custom", "start_date": "2026-02-01", "end_date": "2026-01-01"}
    )

    assert response.status_code == 400


@pytest.mark.parametrize("path", RANGED)
def test_the_widest_valid_custom_range_still_answers(path):
    response = client_for(make_user("admin", make_company())).get(
        path, params={"period": "custom", "start_date": "0001-01-01", "end_date": "9999-12-31"}
    )

    assert response.status_code == 200
