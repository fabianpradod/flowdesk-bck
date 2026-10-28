from uuid import UUID
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from app.api.dependencies.auth import get_db, require_role
from app.models.users import User
from app.schemas.audit import AuditPage
from app.services.audit import list_events

router = APIRouter(prefix='/api/v1/audit', tags=['audit'])


@router.get('/events', response_model=AuditPage, summary='Consultar acciones críticas de la empresa')
def events(
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None, max_length=1024),
    action: str | None = Query(None, max_length=80),
    actor_id: UUID | None = None,
    db: Session = Depends(get_db),
    actor: User = Depends(require_role('admin')),
):
    return list_events(actor, db, limit=limit, cursor=cursor, action=action, actor_id=actor_id)
