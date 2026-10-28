"""Entry point for isolated load tests, never the deployment entry point.

Set DB_SERVER explicitly to loopback, BENCH_SOURCE to the checkout under test,
and seed/migrate the disposable database once before starting worker processes.
Start with uvicorn benchmark_app:app --app-dir scripts ...
"""
import os
import sys
from unittest.mock import patch

if os.environ.get('DB_SERVER') not in {'localhost', '127.0.0.1', '::1'}:
    raise RuntimeError('Benchmark requires an explicit loopback database host')
if not os.environ.get('DB_DATABASE', '').startswith('flowdesk_'):
    raise RuntimeError('Benchmark requires a dedicated flowdesk_ database')
sys.path.insert(0, os.environ['BENCH_SOURCE'])
from app.db import init_db
from app.core.database import get_engine

get_engine()
# Uvicorn workers must not race schema migrations or send demo invitations.
with patch.object(init_db, 'init_db', return_value=None):
    from main import app
