"""Transport security wiring, applied only when FORCE_HTTPS is on.

Everything here is off by default so local development and the test suite keep
working over plain HTTP. Production turns it on through the environment.

Behind a TLS-terminating proxy uvicorn must run with --proxy-headers, otherwise
it sees plain HTTP, and HTTPSRedirectMiddleware redirects in a loop. The
Dockerfile passes it.
"""

from fastapi import FastAPI
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.core import config

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}


def configure_transport_security(app: FastAPI) -> None:
    """Attach host validation, HTTPS redirection and response hardening.

    Settings are read once here rather than per request, so the app cannot
    change transport behaviour halfway through its lifetime.
    """
    allowed_hosts = config.ALLOWED_HOSTS
    force_https = config.FORCE_HTTPS
    hsts_value = f"max-age={config.HSTS_MAX_AGE}; includeSubDomains"

    # add_middleware prepends, so the last one added runs outermost. Redirection
    # is registered first precisely so host validation ends up in front of it:
    # an unknown host must be refused, not redirected to itself over TLS.
    if force_https:
        app.add_middleware(HTTPSRedirectMiddleware)

    if allowed_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.middleware("http")
    async def _security_headers(request, call_next):
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        if force_https:
            # Only meaningful over TLS, and harmful while still on plain HTTP:
            # a browser that sees it refuses http:// access to the host after.
            response.headers.setdefault("Strict-Transport-Security", hsts_value)
        return response
