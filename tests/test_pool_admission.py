import asyncio
import threading
import time

import anyio.to_thread
import httpx
from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse

from app.core.config import DB_MAX_OVERFLOW, DB_POOL_SIZE
from app.core.pool_admission import PoolAdmissionMiddleware


class SlowApp:
    """Plain ASGI app that records how many requests are inside at once."""

    def __init__(self):
        self.inside = 0
        self.peak = 0
        self.release = asyncio.Event()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            self.lifespan = scope["type"]
            return
        self.inside += 1
        self.peak = max(self.peak, self.inside)
        if scope["path"] != "/health":
            await self.release.wait()
        self.inside -= 1
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


def client_for(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def test_limits_requests_inside_the_app():
    async def scenario():
        inner = SlowApp()
        async with client_for(PoolAdmissionMiddleware(inner, limit=2)) as client:
            requests = [asyncio.create_task(client.get("/api/v1/inventory/products")) for _ in range(6)]
            await asyncio.sleep(0.1)
            assert inner.inside == 2
            inner.release.set()
            responses = await asyncio.wait_for(asyncio.gather(*requests), 3)
        assert inner.peak == 2
        assert all(response.status_code == 200 for response in responses)

    asyncio.run(scenario())


def test_health_is_not_limited():
    async def scenario():
        inner = SlowApp()
        async with client_for(PoolAdmissionMiddleware(inner, limit=1)) as client:
            busy = asyncio.create_task(client.get("/api/v1/tasks"))
            await asyncio.sleep(0.05)
            health = await asyncio.wait_for(client.get("/health"), 1)
            assert health.status_code == 200
            assert not busy.done()
            inner.release.set()
            await busy

    asyncio.run(scenario())


def test_other_scopes_pass_through():
    async def scenario():
        inner = SlowApp()
        await PoolAdmissionMiddleware(inner, limit=1)({"type": "lifespan"}, None, None)
        assert inner.lifespan == "lifespan"

    asyncio.run(scenario())


def test_main_app_admits_as_many_requests_as_pool_connections():
    from main import app

    admission = [m for m in app.user_middleware if m.cls is PoolAdmissionMiddleware]
    assert len(admission) == 1
    assert admission[0].kwargs["limit"] == DB_POOL_SIZE + DB_MAX_OVERFLOW


def build_pool_app(pool_size, timeout=1.0):
    """Same shape as the real routes: a sync yield dependency that holds a pooled
    connection until the response is sent, a second sync dependency, a sync endpoint."""
    pool = threading.BoundedSemaphore(pool_size)
    app = FastAPI()

    @app.exception_handler(TimeoutError)
    async def pool_timeout(_request, _exc):
        return JSONResponse(status_code=500, content={"code": "pool_timeout"})

    def get_conn():
        if not pool.acquire(timeout=timeout):
            raise TimeoutError("pool exhausted")
        try:
            yield
        finally:
            pool.release()

    def current_user(conn=Depends(get_conn)):
        return "user"

    def checker(user=Depends(current_user)):
        return user

    @app.get("/api/work")
    def work(user=Depends(checker), conn=Depends(get_conn)):
        time.sleep(0.005)
        return {"user": user}

    return app


def run_burst(app, requests=40, threads=4):
    async def scenario():
        anyio.to_thread.current_default_thread_limiter().total_tokens = threads
        async with client_for(app) as client:
            return await asyncio.gather(*(client.get("/api/work") for _ in range(requests)))

    return asyncio.run(scenario())


def test_requests_beyond_the_pool_wait_instead_of_starving_the_threads():
    pool_size = 2
    app = PoolAdmissionMiddleware(build_pool_app(pool_size), limit=pool_size)

    responses = run_burst(app)

    assert [response.status_code for response in responses] == [200] * len(responses)
