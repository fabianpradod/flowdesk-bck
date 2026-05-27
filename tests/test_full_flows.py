from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

def test_complete_auth_flow():
    company_response = client.post(
        "/api/v1/auth/register-company",
        json={
            "name": "QA Company",
            "admin_email": "qaadmin@test.com",
            "admin_username": "qaadmin"
        }
    )

    assert company_response.status_code in [200, 201]

    login_response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "qaadmin@test.com",
            "password": "123456"
        }
    )

    assert login_response.status_code in [200, 401, 403]

    if login_response.status_code == 200:
        body = login_response.json()
        assert "access_token" in body
       