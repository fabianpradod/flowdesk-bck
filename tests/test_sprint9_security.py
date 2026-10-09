"""Sprint 9: actual response headers, docs compatibility and CORS boundaries."""
import base64
import hashlib
import re

import pytest
from fastapi.testclient import TestClient
from starlette.responses import StreamingResponse

from app.core import config
from app.core.https import API_CSP, SECURITY_HEADERS, SecureFastAPI


def assert_hardened(response):
    for header, value in SECURITY_HEADERS.items():
        assert response.headers[header] == value


@pytest.mark.parametrize('path,status', [
    ('/health', 200), ('/openapi.json', 200), ('/missing', 404),
    ('/api/v1/users', 401),
])
def test_api_and_errors_have_restrictive_csp(client, path, status):
    response = client.get(path)
    assert response.status_code == status
    assert_hardened(response)


def test_server_error_is_also_hardened(monkeypatch):
    from tests.security_helpers import client_for, make_company, make_user

    def fail(*args, **kwargs):
        raise RuntimeError('private database details')

    monkeypatch.setattr('app.services.inventory.list_products', fail)
    response = client_for(make_user('employee', make_company())).get(
        '/api/v1/inventory/products', headers={'Origin': config.CORS_ORIGINS[0]},
    )
    assert response.headers['access-control-allow-origin'] == config.CORS_ORIGINS[0]
    assert response.status_code == 500
    assert 'private database details' not in response.text
    assert_hardened(response)


@pytest.mark.parametrize('path', ['/docs', '/redoc', '/docs/oauth2-redirect'])
def test_documentation_inline_scripts_are_authorized_by_exact_hash(client, path):
    response = client.get(path)
    assert response.status_code == 200
    policy = response.headers['content-security-policy']
    assert "frame-ancestors 'none'" in policy
    script_policy = next(part for part in policy.split(';') if part.strip().startswith('script-src '))
    assert "'unsafe-inline'" not in script_policy
    assert "'unsafe-eval'" not in script_policy
    assert 'https://cdn.jsdelivr.net' in script_policy
    for attrs, script in re.findall(r'<script([^>]*)>(.*?)</script>', response.text, re.S):
        if 'src=' not in attrs:
            digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
            assert f"'sha256-{digest}'" in script_policy


def test_cors_allows_frontend_preflight_with_security_headers(client):
    origin = config.CORS_ORIGINS[0]
    response = client.options('/api/v1/inventory/products', headers={
        'Origin': origin, 'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'authorization,content-type',
    })
    assert response.status_code == 200
    assert response.headers['access-control-allow-origin'] == origin
    assert response.headers['access-control-allow-credentials'] == 'true'
    assert_hardened(response)


@pytest.mark.parametrize('origin', ['https://evil.example', 'null', 'http://localhost:5173.evil.example'])
def test_cors_rejects_other_origins(client, origin):
    response = client.options('/api/v1/inventory/products', headers={
        'Origin': origin, 'Access-Control-Request-Method': 'POST',
    })
    assert response.status_code == 400
    assert 'access-control-allow-origin' not in response.headers
    assert_hardened(response)
    # CORS does not reject simple HTTP requests, but browsers cannot read them.
    response = client.get('/health', headers={'Origin': origin})
    assert 'access-control-allow-origin' not in response.headers


def test_cors_rejects_unneeded_headers_and_methods(client):
    for method, headers in [('TRACE', 'authorization'), ('POST', 'x-unexpected')]:
        response = client.options('/health', headers={
            'Origin': config.CORS_ORIGINS[0], 'Access-Control-Request-Method': method,
            'Access-Control-Request-Headers': headers,
        })
        assert response.status_code == 400


def test_cors_environment_override_removes_localhost(monkeypatch):
    import importlib
    with monkeypatch.context() as patch:
        patch.setenv('CORS_ORIGINS', 'https://app.example.com')
        importlib.reload(config)
        assert config.CORS_ORIGINS == ['https://app.example.com']
    importlib.reload(config)


def test_streamed_download_body_is_preserved():
    api = SecureFastAPI()

    @api.get('/download')
    def download():
        return StreamingResponse(iter([b'first,', b'second\n']), media_type='text/csv')

    response = TestClient(api).get('/download')
    assert response.content == b'first,second\n'
    assert response.headers['content-security-policy'] == API_CSP


def test_docs_csp_works_behind_a_proxy_path_prefix():
    api = SecureFastAPI(root_path='/service')
    response = TestClient(api).get('/service/docs')
    assert response.status_code == 200
    assert 'sha256-' in response.headers['content-security-policy']
    assert '/service/openapi.json' in response.text
