"""Private manager/admin assistant and saved conversation endpoints."""
import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.dependencies.ai import get_chat_provider, get_chat_db
from app.api.dependencies.auth import require_role
from app.schemas.chat import ChatRequest, ChatResponse, ConversationDetail, ConversationList
from app.services.chat import answer_chat
from app.services.chat_store import ChatActor, ConversationStore
from app.tenancy.runtime import get_user_schema_name

router = APIRouter(prefix="/api/v1/ai", tags=["AI chat"])


def get_chat_actor(user=Depends(require_role("manager", "admin", strict=True))):
    return ChatActor(user_id=user.id, schema_name=get_user_schema_name(user))


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest, actor=Depends(get_chat_actor), db: Session = Depends(get_chat_db),
         provider=Depends(get_chat_provider)):
    # Sync SQLAlchemy stays on FastAPI's worker thread, including across model awaits.
    return asyncio.run(answer_chat(request, db=db, actor=actor, provider=provider))


@router.get("/conversations", response_model=ConversationList)
def list_conversations(limit: int = Query(20, ge=1, le=100), cursor: str | None = Query(None, max_length=512),
                       actor=Depends(get_chat_actor), db: Session = Depends(get_chat_db)):
    return ConversationStore(db, actor).list(limit=limit, cursor=cursor)


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
def get_conversation(conversation_id: UUID, limit: int = Query(50, ge=1, le=100),
                     cursor: str | None = Query(None, max_length=512),
                     actor=Depends(get_chat_actor), db: Session = Depends(get_chat_db)):
    return ConversationStore(db, actor).detail(conversation_id, limit=limit, cursor=cursor)


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: UUID, actor=Depends(get_chat_actor), db: Session = Depends(get_chat_db)):
    ConversationStore(db, actor).delete(conversation_id)
    return Response(status_code=204)
