"""Integration 1 — Authentication: API + auth service + JWT + PostgreSQL.

Components: FastAPI route POST /api/v1/auth/login, app.services.auth, bcrypt
password check, JWT issuing, the get_current_user dependency, SQLAlchemy and
the global.users / tenant producto tables in PostgreSQL.
"""
from integration_helpers import ADMIN_EMAIL, DEMO_PASSWORD, login


def test_login_issues_token_that_opens_tenant_data(client):
    # 1. Credentials are checked against the user row stored by the seeder.
    response = login(client, ADMIN_EMAIL, DEMO_PASSWORD)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"]
    assert body["token_type"].lower() == "bearer"

    # 2. The issued JWT is accepted by a protected route, which resolves the user
    #    from the database and reads the products of that user's tenant schema.
    products = client.get(
        "/api/v1/inventory/products",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )

    assert products.status_code == 200, products.text
    skus = {product["sku"] for product in products.json()}
    assert {"DEMO-ARROZ", "DEMO-FRIJOL", "DEMO-CAFE"} <= skus


def test_login_rejects_wrong_password_and_token_is_required(client):
    response = login(client, ADMIN_EMAIL, "WrongPassword!1")
    assert response.status_code == 401
    assert "access_token" not in response.json()

    unauthenticated = client.get("/api/v1/inventory/products")
    assert unauthenticated.status_code == 401
