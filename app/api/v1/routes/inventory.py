import app.services.inventory as inventory_service

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from uuid import UUID

from app.api.dependencies.auth import get_current_user, get_db, require_role
from app.models.users import User
from app.schemas.inventory import (
    InventoryAlertResponse,
    InventoryMovementCreate,
    InventoryMovementResponse,
    ProductCreate,
    ProductResponse,
    SupplierCreate,
    SupplierResponse,
)


router = APIRouter(prefix="/api/v1/inventory", tags=["inventory"])


@router.get("/suppliers", response_model=list[SupplierResponse])
def list_suppliers(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return inventory_service.list_suppliers(current_user, db)


@router.post("/suppliers", response_model=SupplierResponse)
def create_supplier(
    data: SupplierCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("manager")),
):
    return inventory_service.create_supplier(data, current_user, db)


@router.get("/products", response_model=list[ProductResponse])
def list_products(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return inventory_service.list_products(current_user, db)


@router.post("/products", response_model=ProductResponse)
def create_product(
    data: ProductCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("manager")),
):
    return inventory_service.create_product(data, current_user, db)


@router.get("/movements", response_model=list[InventoryMovementResponse])
def list_movements(
    product_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return inventory_service.list_inventory_movements(current_user, db, product_id)


@router.post("/movements", response_model=InventoryMovementResponse)
def create_movement(
    data: InventoryMovementCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("manager")),
):
    return inventory_service.create_inventory_movement(data, current_user, db)


@router.get("/alerts", response_model=list[InventoryAlertResponse])
def list_alerts(
    open_only: bool = Query(default=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return inventory_service.list_inventory_alerts(current_user, db, open_only=open_only)
