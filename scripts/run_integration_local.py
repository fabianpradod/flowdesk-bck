"""Run the CI integration tests locally using a disposable Docker PostgreSQL."""
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx

root = Path(__file__).resolve().parents[1]
os.chdir(root)
reports = root / "reports"
reports.mkdir(exist_ok=True)
name = f"flowdesk-ci-{uuid4().hex[:12]}"
api = None
env = os.environ.copy()
env.update({
    "DB_SERVER": "127.0.0.1", "DB_DATABASE": "flowdesk_ci",
    "DB_USERNAME": "flowdesk_ci", "DB_PASSWORD": "ci-only-password",
    "SECRET_KEY": "ci-only-signing-key-for-disposable-tests",
    "SUPERADMIN_EMAIL": "superadmin@example.com", "SUPERADMIN_USERNAME": "superadmin",
    "SUPERADMIN_PASSWORD": "CiPassword123!", "DEMO_SEED_ENABLED": "true",
    "DEMO_USER_PASSWORD": "Demo12345!", "SMTP_USERNAME": "ci@example.com",
    "SMTP_PASSWORD": "unused-in-ci", "FRONTEND_URL": "http://localhost:5173",
    "ZAI_API_KEY": "", "FORCE_HTTPS": "false", "ALLOWED_HOSTS": "",
})
try:
    subprocess.run([
        "docker", "run", "--rm", "--detach", "--name", name,
        "-p", "127.0.0.1::5432", "-e", "POSTGRES_USER=flowdesk_ci",
        "-e", "POSTGRES_PASSWORD=ci-only-password", "-e", "POSTGRES_DB=flowdesk_ci",
        "postgres:16",
    ], check=True)
    env["DB_PORT"] = subprocess.check_output(["docker", "port", name, "5432/tcp"], text=True).strip().rsplit(":", 1)[1]
    for _ in range(60):
        if subprocess.run(["docker", "exec", name, "pg_isready", "-U", "flowdesk_ci", "-d", "flowdesk_ci"], capture_output=True).returncode == 0:
            break
        time.sleep(1)
    else:
        raise RuntimeError("PostgreSQL did not become ready in 60 seconds")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env["CI_API_URL"] = f"http://127.0.0.1:{port}"
    with (reports / "api.log").open("w") as output:
        api = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(port)], env=env, stdout=output, stderr=subprocess.STDOUT)
        for _ in range(60):
            if api.poll() is not None:
                raise RuntimeError("API stopped during startup; see reports/api.log")
            try:
                if httpx.get(env["CI_API_URL"] + "/ready", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        else:
            raise RuntimeError("API did not become ready in 60 seconds")
        result = subprocess.run([sys.executable, "-m", "pytest", "integration", "-v", "--junitxml=reports/integration.xml"], env=env)
        raise SystemExit(result.returncode)
finally:
    if api is not None and api.poll() is None:
        api.terminate()
        try:
            api.wait(timeout=10)
        except subprocess.TimeoutExpired:
            api.kill()
            api.wait()
    subprocess.run(["docker", "rm", "--force", name], capture_output=True)
