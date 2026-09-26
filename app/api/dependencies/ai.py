"""Lazy provider configuration, usable with FastAPI dependency overrides."""

from fastapi import Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from app.api.dependencies.auth import get_db
from app.services.chat_store import limit_transaction

from app.core import config
from app.integrations.chat_provider import ChatProvider
from app.integrations.zai_chat import ZAIChatProvider
from app.utils.exceptions import AppError


def get_chat_provider() -> ChatProvider:
    try:
        max_tokens = int(config.ZAI_CHAT_MAX_TOKENS)
    except (TypeError, ValueError) as exc:
        raise AppError(503, "Chat provider configuration is invalid", "ai_provider_misconfigured") from exc
    return ZAIChatProvider(
        api_key=config.ZAI_API_KEY,
        model=config.ZAI_MODEL,
        base_url=config.ZAI_BASE_URL,
        timeout_seconds=config.ZAI_TIMEOUT_SECONDS,
        max_tokens=max_tokens,
    )


def get_chat_db(db: Session = Depends(get_db)):
    """Bound database waits and sanitize storage errors across all chat routes."""
    try:
        limit_transaction(db)
        yield db
    except SQLAlchemyError as exc:
        raise AppError(503, "Chat storage is temporarily unavailable", "ai_data_unavailable") from exc
    finally:
        db.rollback()
