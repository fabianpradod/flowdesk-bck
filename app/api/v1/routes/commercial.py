from uuid import UUID

import app.services.commercial as commercial_service
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user, get_db, require_role
from app.models.users import User
from app.schemas.commercial import (
    ClientCreate,
    ClientResponse,
    ClientStatusUpdate,
    ClientUpdate,
    SaleCreate,
    SaleResponse,
)

router = APIRouter(prefix="/api/v1/commercial", tags=["commercial"])


@router.get("/clients", response_model=list[ClientResponse], summary="Listar clientes")
def clients(
    search: str | None = Query(default=None),
    active_only: bool = Query(default=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retorna los clientes del esquema de la empresa autenticada. Permite buscar por nombre, correo o teléfono."""
    return commercial_service.list_clients(
        current_user,
        db,
        search=search,
        active_only=active_only,
    )


@router.get("/clients/{client_id}", response_model=ClientResponse, summary="Obtener cliente")
def client_detail(
    client_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retorna un cliente por id dentro del esquema de la empresa autenticada."""
    return commercial_service.get_client(client_id, current_user, db)


@router.post("/clients", response_model=ClientResponse, summary="Crear cliente")
def create_client(
    data: ClientCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("manager")),
):
    """Crea un cliente en el esquema de la empresa autenticada. Requiere rol manager o superior."""
    return commercial_service.create_client(data, current_user, db)


@router.put("/clients/{client_id}", response_model=ClientResponse, summary="Actualizar cliente")
def update_client(
    client_id: UUID,
    data: ClientUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("manager")),
):
    """Actualiza los datos de un cliente del esquema de la empresa autenticada. Requiere rol manager o superior."""
    return commercial_service.update_client(client_id, data, current_user, db)


@router.patch("/clients/{client_id}/status", response_model=ClientResponse, summary="Actualizar estado de cliente")
def update_client_status(
    client_id: UUID,
    data: ClientStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("manager")),
):
    """Activa o desactiva un cliente sin eliminar su registro. Requiere rol manager o superior."""
    return commercial_service.update_client_status(client_id, data.is_active, current_user, db)


@router.delete("/clients/{client_id}", status_code=204, summary="Eliminar cliente")
def delete_client(
    client_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("manager")),
):
    """Desactiva un cliente del esquema de la empresa autenticada. Requiere rol manager o superior."""
    commercial_service.delete_client(client_id, current_user, db)


@router.post("/sales", response_model=SaleResponse, status_code=201, summary="Registrar venta")
def create_sale(
    data: SaleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role()),
):
    """Registra una venta para un cliente activo o, sin cliente_id, para consumidor final."""
    return commercial_service.create_sale(data, current_user, db)


@router.get("/sales/{sale_id}", response_model=SaleResponse, summary="Obtener venta")
def sale_detail(
    sale_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role()),
):
    return commercial_service.get_sale(sale_id, current_user, db)


@router.get(
    "/clients/{client_id}/purchases",
    response_model=list[SaleResponse],
    summary="Historial de compras del cliente",
)
def client_purchases(
    client_id: UUID,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role()),
):
    return commercial_service.list_client_purchases(
        client_id,
        current_user,
        db,
        limit=limit,
        offset=offset,
    )
