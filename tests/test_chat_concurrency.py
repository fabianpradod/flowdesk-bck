"""One ASGI event loop shares the real AnyIO worker pool across concurrent requests."""
import asyncio
from datetime import timedelta
from threading import Event, Lock
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import Header

from app.api.dependencies.ai import get_chat_db, get_chat_provider
from app.api.v1.routes.chat import get_chat_actor
from app.integrations.chat_provider import ChatCompletion
from app.services.chat_store import ChatActor, utcnow
from app.utils.exceptions import AppError
from main import app


class GatedProvider:
    def __init__(self):
        self.release = Event()
        self.lock = Lock()
        self.calls = 0
        self.failure = None

    async def complete(self, **kwargs):
        with self.lock:
            self.calls += 1
        # Keep model calls pending until the test has probed the rest of the API.
        while not self.release.is_set():
            await asyncio.sleep(0.01)
        if self.failure:
            raise self.failure
        return ChatCompletion(content="Ready", tool_calls=[], assistant_message={})


@pytest.fixture
def chat_app(monkeypatch):
    from app.services import chat

    class Store:
        def __init__(self, *args):
            pass

        def append_turn(self, **kwargs):
            now = utcnow()
            return uuid4(), uuid4(), now, now + timedelta(days=15)

    class DB:
        def rollback(self):
            pass

    provider = GatedProvider()
    schema = f"tenant_{uuid4().hex}"

    def actor(x_user: UUID = Header()):
        return ChatActor(x_user, schema)

    monkeypatch.setattr(chat, "ConversationStore", Store)
    monkeypatch.setattr(chat, "limit_transaction", lambda *args: None)
    app.dependency_overrides[get_chat_actor] = actor
    app.dependency_overrides[get_chat_db] = DB
    app.dependency_overrides[get_chat_provider] = lambda: provider
    yield provider
    provider.release.set()


async def wait_for_calls(provider, expected):
    async with asyncio.timeout(3):
        while provider.calls < expected:
            await asyncio.sleep(0.01)


def post(client, user):
    return client.post("/api/v1/ai/chat", headers={"x-user": str(user)}, json={"message": "Hello"})


@pytest.mark.parametrize("same_user,admitted", [(True, 1), (False, 8)])
def test_excess_chats_are_rejected_while_health_stays_responsive(chat_app, same_user, admitted):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            users = [uuid4() for _ in range(admitted)]
            active = [asyncio.create_task(post(client, user)) for user in users]
            try:
                await wait_for_calls(chat_app, admitted)
                excess = [post(client, users[0] if same_user else uuid4()) for _ in range(45 - admitted)]
                # All these responses must arrive BEFORE any admitted chat is released.
                responses = await asyncio.wait_for(asyncio.gather(*excess, client.get("/health")), 3)
                assert all(response.status_code == 429 for response in responses[:-1])
                assert all(response.json()["code"] == "ai_chat_busy" for response in responses[:-1])
                assert responses[-1].status_code == 200
                assert responses[-1].json() == {"status": "ok"}
                assert chat_app.calls == admitted  # rejected requests never invoke the provider
                assert all(not task.done() for task in active)
            finally:
                chat_app.release.set()
                completed = await asyncio.gather(*active, return_exceptions=True)
            assert all(response.status_code == 200 for response in completed)
            # Success releases both global capacity and the same user's slot.
            assert (await post(client, users[0])).status_code == 200
    asyncio.run(scenario())


@pytest.mark.parametrize("failure,status", [
    (AppError(502, "Upstream failed", "ai_provider_error"), 502),
    (TimeoutError(), 504),
    (RuntimeError("Unexpected failure"), 500),
])
def test_failed_chat_releases_user_and_global_slots(chat_app, failure, status):
    async def scenario():
        chat_app.release.set()
        chat_app.failure = failure
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                     base_url="http://test") as client:
            user = uuid4()
            # More failures than total capacity detects leaking the global semaphore too.
            for _ in range(10):
                assert (await post(client, user)).status_code == status
            chat_app.failure = None
            assert (await post(client, user)).status_code == 200
    asyncio.run(scenario())


def test_cancelled_worker_releases_its_slot(chat_app, monkeypatch):
    from app.api.v1.routes import chat as routes
    from app.schemas.chat import ChatRequest

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError()

    actor = ChatActor(uuid4(), f"tenant_{uuid4().hex}")
    with monkeypatch.context() as patch:
        patch.setattr(routes, "answer_chat", cancelled)
        for _ in range(10):
            with pytest.raises(asyncio.CancelledError):
                routes.chat(ChatRequest(message="Hello"), actor=actor, db=None, provider=None)
    # Use the identical authenticated actor after cancellation to prove both slots were freed.
    app.dependency_overrides[get_chat_actor] = lambda: actor
    chat_app.release.set()

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            assert (await post(client, actor.user_id)).status_code == 200
    asyncio.run(scenario())
