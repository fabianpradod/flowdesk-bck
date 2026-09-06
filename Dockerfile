FROM python:3.11.16-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --requirement requirements.txt \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin flowdesk

COPY --chown=flowdesk:flowdesk . .

USER flowdesk

EXPOSE 8000

# --proxy-headers makes uvicorn honour X-Forwarded-Proto. Without it the app
# sees plain HTTP behind a TLS-terminating proxy and HTTPSRedirectMiddleware
# would redirect in a loop.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
