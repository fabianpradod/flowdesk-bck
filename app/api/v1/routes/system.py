from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_db
from app.utils.exceptions import AppError
from app.utils.logger import logger


router = APIRouter(tags=["system"])


@router.get("/health", summary="Estado del proceso")
def health():
    return {"status": "ok"}


@router.get("/ready", summary="Estado de dependencias")
def readiness(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:
        # Probes hit this every few seconds, so log the cause without a traceback.
        logger.warning("Readiness check failed: %s", exc.__class__.__name__)
        raise AppError(status_code=503, message="Database is not ready", code="not_ready")
    return {"status": "ready"}
