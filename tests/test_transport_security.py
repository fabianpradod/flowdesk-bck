"""Transport security is env-gated, so each case configures an app under patched settings.

configure_transport_security reads the settings once, at configuration time, so
the patch only has to be active while the app is being built.
"""

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import config
from app.core.https import SECURITY_HEADERS, configure_transport_security


def build_app(force_https=False, allowed_hosts=None, hsts_max_age=63072000):
    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"ok": True}

    with patch.multiple(
        config,
        FORCE_HTTPS=force_https,
        ALLOWED_HOSTS=allowed_hosts or [],
        HSTS_MAX_AGE=hsts_max_age,
    ):
        configure_transport_security(app)
    return app


def client(app, base_url="http://testserver"):
    return TestClient(app, base_url=base_url)


# ─── the default: nothing changes for local development ───────────────────────

def test_plain_http_still_works_when_the_flag_is_off():
    response = client(build_app()).get("/ping")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_hsts_is_not_sent_while_https_is_not_forced():
    """Sending it over plain HTTP would lock a browser out of the host."""
    response = client(build_app()).get("/ping")

    assert "Strict-Transport-Security" not in response.headers


def test_an_empty_host_list_accepts_any_host():
    response = client(build_app(), "http://whatever.example.com").get("/ping")

    assert response.status_code == 200


# ─── hardening headers apply either way ───────────────────────────────────────

def test_hardening_headers_are_always_present():
    response = client(build_app()).get("/ping")

    for header, value in SECURITY_HEADERS.items():
        assert response.headers[header] == value


# ─── with FORCE_HTTPS on ──────────────────────────────────────────────────────

def test_http_is_redirected_to_https_when_forced():
    response = client(build_app(force_https=True)).get("/ping", follow_redirects=False)

    assert response.status_code in (301, 307, 308)
    assert response.headers["location"].startswith("https://")


def test_hsts_is_sent_over_https_when_forced():
    response = client(build_app(force_https=True), "https://testserver").get("/ping")

    header = response.headers["Strict-Transport-Security"]

    assert header.startswith("max-age=63072000")
    assert "includeSubDomains" in header


def test_the_hsts_lifetime_is_configurable():
    app = build_app(force_https=True, hsts_max_age=600)

    response = client(app, "https://testserver").get("/ping")

    assert response.headers["Strict-Transport-Security"].startswith("max-age=600")


# ─── host validation ──────────────────────────────────────────────────────────

def test_an_unexpected_host_is_rejected_when_a_list_is_configured():
    app = build_app(allowed_hosts=["api.flowdesk.com"])

    response = client(app, "http://evil.example.com").get("/ping")

    assert response.status_code == 400


def test_a_listed_host_is_accepted():
    app = build_app(allowed_hosts=["api.flowdesk.com"])

    response = client(app, "http://api.flowdesk.com").get("/ping")

    assert response.status_code == 200


def test_host_validation_and_redirection_combine():
    app = build_app(force_https=True, allowed_hosts=["api.flowdesk.com"])

    rejected = client(app, "http://evil.example.com").get("/ping", follow_redirects=False)
    redirected = client(app, "http://api.flowdesk.com").get("/ping", follow_redirects=False)

    assert rejected.status_code == 400
    assert redirected.status_code in (301, 307, 308)


# ─── the settings themselves ──────────────────────────────────────────────────

def test_https_is_off_by_default():
    """Turning it on by default would break local dev and the rest of the suite."""
    assert config.FORCE_HTTPS is False
    assert config.ALLOWED_HOSTS == []
