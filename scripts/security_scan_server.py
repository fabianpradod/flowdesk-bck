"""Local read-only ZAP target with real routes and no database initialization.

Usage: .venv/bin/python scripts/security_scan_server.py PORT [SOURCE_CHECKOUT]
This HTTP/TestClient bridge is for passive security scans, never deployment.
"""
import sys
from pathlib import Path
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
sys.path.insert(0, sys.argv[2] if len(sys.argv) > 2 else str(Path(__file__).resolve().parents[1]))
from app.db import init_db
with patch.object(init_db, 'init_db', return_value=None):
    from main import app
from app.api.dependencies.auth import get_db
from fastapi.testclient import TestClient
class OfflineDB:
    def execute(self, *args, **kwargs):
        raise RuntimeError('Isolated security scan: database disabled')
    def query(self, *args, **kwargs):
        raise RuntimeError('Isolated security scan: database disabled')
app.dependency_overrides[get_db] = lambda: OfflineDB()
client = TestClient(app, raise_server_exceptions=False)
class Handler(BaseHTTPRequestHandler):
    def forward(self):
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        headers = dict(self.headers)
        response = client.request(self.command, self.path, headers=headers, content=body, follow_redirects=False)
        self.send_response_only(response.status_code)
        for name, value in response.headers.items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(response.content)
    # Passive baseline only. Mutation methods never reach application services.
    do_GET = do_HEAD = do_OPTIONS = forward
    def log_message(self, *args):
        pass
print('Isolated HTTP/TestClient bridge ready', flush=True)
ThreadingHTTPServer(('0.0.0.0', int(sys.argv[1])), Handler).serve_forever()
