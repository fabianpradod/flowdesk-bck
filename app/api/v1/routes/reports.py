import app.services.reports as reports_service

from datetime import date
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from io import BytesIO
from sqlalchemy.orm import Session
from uuid import UUID

from app.api.dependencies.auth import get_db, require_role
from app.models.users import User
from app.schemas.inventory import AnalyticsPeriod, MovementType
from app.schemas.reports import REPORT_MEDIA_TYPES, ReportFormat, ReportHistoryRow, ReportType

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


@router.get("/history", response_model=list[ReportHistoryRow], summary="Historial de reportes")
def report_history(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Retorna los reportes generados por la empresa, del más reciente al más antiguo. Requiere rol admin o superior."""
    return reports_service.list_report_history(current_user, db, limit=limit)


@router.get("/inventario", summary="Reporte de inventario")
def inventory_report(
    format: ReportFormat = Query(default="csv"),
    product_id: UUID | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    only_low_stock: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Descarga el inventario actual en CSV o PDF. Filtrable por producto, estado y con ?only_low_stock=true para ver solo productos en o bajo el mínimo. Requiere rol admin o superior."""
    dataset = reports_service.build_inventory_dataset(
        current_user,
        db,
        product_id=product_id,
        is_active=is_active,
        only_low_stock=only_low_stock,
    )
    return _download(dataset, current_user, db, report_type="inventario", report_format=format)


@router.get("/movimientos", summary="Reporte de movimientos")
def movements_report(
    format: ReportFormat = Query(default="csv"),
    period: AnalyticsPeriod = Query(default="30d"),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    product_id: UUID | None = Query(default=None),
    movement_type: MovementType | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Descarga los movimientos de inventario del período en CSV o PDF. Usar ?period=custom junto con start_date y end_date para un rango propio. Requiere rol admin o superior."""
    dataset = reports_service.build_movements_dataset(
        current_user,
        db,
        period=period,
        start_date=start_date,
        end_date=end_date,
        product_id=product_id,
        movement_type=movement_type,
    )
    return _download(dataset, current_user, db, report_type="movimientos", report_format=format)


@router.get("/alertas", summary="Reporte de alertas")
def alerts_report(
    format: ReportFormat = Query(default="csv"),
    period: AnalyticsPeriod = Query(default="30d"),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    open_only: bool = Query(default=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """Descarga las alertas de inventario del período en CSV o PDF. Por defecto solo incluye alertas abiertas; usar ?open_only=false para incluir las resueltas. Requiere rol admin o superior."""
    dataset = reports_service.build_alerts_dataset(
        current_user,
        db,
        period=period,
        start_date=start_date,
        end_date=end_date,
        open_only=open_only,
    )
    return _download(dataset, current_user, db, report_type="alertas", report_format=format)


def _download(
    dataset,
    current_user: User,
    db: Session,
    *,
    report_type: ReportType,
    report_format: ReportFormat,
) -> StreamingResponse:
    payload, filename = reports_service.generate_report(
        dataset,
        current_user,
        db,
        report_type=report_type,
        report_format=report_format,
    )
    return StreamingResponse(
        BytesIO(payload),
        media_type=REPORT_MEDIA_TYPES[report_format],
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(payload)),
        },
    )
