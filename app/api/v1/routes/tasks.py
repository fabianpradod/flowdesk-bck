from uuid import UUID

import app.services.tasks as task_service
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user, get_db
from app.models.users import User
from app.schemas.tasks import (
    TaskCreate,
    TaskPriority,
    TaskResponse,
    TaskStatus,
    TaskStatusUpdate,
    TaskUpdate,
)


router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskResponse], summary="Listar tareas")
def tasks(
    estado: TaskStatus | None = Query(default=None),
    prioridad: TaskPriority | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista únicamente las tareas del usuario autenticado, con filtros opcionales."""
    return task_service.list_tasks(
        current_user,
        db,
        estado=estado,
        prioridad=prioridad,
        search=search,
    )


@router.get("/{task_id}", response_model=TaskResponse, summary="Obtener tarea")
def task_detail(
    task_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Obtiene una tarea por id cuando pertenece al usuario autenticado."""
    return task_service.get_task(task_id, current_user, db)


@router.post(
    "",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear tarea",
)
def create_task(
    data: TaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Crea una tarea pendiente para el usuario autenticado."""
    return task_service.create_task(data, current_user, db)


@router.put("/{task_id}", response_model=TaskResponse, summary="Actualizar tarea")
def update_task(
    task_id: UUID,
    data: TaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Actualiza los campos enviados de una tarea propia."""
    return task_service.update_task(task_id, data, current_user, db)


@router.patch(
    "/{task_id}/status",
    response_model=TaskResponse,
    summary="Cambiar estado de tarea",
)
def update_task_status(
    task_id: UUID,
    data: TaskStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cambia el estado de una tarea propia."""
    return task_service.update_task_status(
        task_id,
        data.estado,
        current_user,
        db,
    )


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar tarea",
)
def delete_task(
    task_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Elimina una tarea propia de forma permanente."""
    task_service.delete_task(task_id, current_user, db)
