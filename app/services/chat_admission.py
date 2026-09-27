"""Process-local admission: leave worker capacity for the rest of the API."""
from contextlib import contextmanager
from threading import BoundedSemaphore, Lock

from app.services.chat_store import ChatActor
from app.utils.exceptions import AppError

MAX_IN_FLIGHT = 8
_slots = BoundedSemaphore(MAX_IN_FLIGHT)
_lock = Lock()
_active_users: set[ChatActor] = set()


@contextmanager
def admit_chat(actor: ChatActor):
    # Only bookkeeping runs under the lock. Never queue for a model-call slot.
    with _lock:
        if actor in _active_users:
            raise AppError(429, "A chat request is already in progress for this user", "ai_chat_busy")
        if not _slots.acquire(blocking=False):
            raise AppError(429, "Chat is busy; try again after an active request finishes", "ai_chat_busy")
        _active_users.add(actor)
    try:
        yield
    finally:
        with _lock:
            _active_users.remove(actor)
            _slots.release()
