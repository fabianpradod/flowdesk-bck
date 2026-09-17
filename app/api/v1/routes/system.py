from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_db


router = APIRouter(tags=["system"])


@router.get("/health", summary="Estado del proceso")
def health():
    return {"status": "ok"}


@router.get("/ready", summary="Estado de dependencias")
def readiness(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ready"}
