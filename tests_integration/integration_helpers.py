"""Shared helpers for the integration tests (kept out of conftest.py on purpose)."""
import os

from sqlalchemy import select

ADMIN_EMAIL = "admin.demo@flowdesk.com"
MANAGER_EMAIL = "manager.demo@flowdesk.com"
DEMO_PASSWORD = os.environ.get("DEMO_USER_PASSWORD", "Demo12345!")


def login(client, email: str, password: str = DEMO_PASSWORD):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def auth_headers(client, email: str) -> dict:
    response = login(client, email)
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def product_by_sku(db, tenant_tables, sku: str):
    products = tenant_tables["producto"]
    return db.execute(select(products).where(products.c.sku == sku)).mappings().one()
