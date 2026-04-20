from fastapi import HTTPException, Depends

def require_permission(permission_name: str):
    def permission_checker(current_user = Depends(get_current_user))
        user_permissions = [p.name for p in current_user.permissions]

        if permission_name not in user_permissions:
            raise HTTPException(
                status_code = 403,
                detail = "No tienes permisos para esta acción"
            )
        return current_user
    return permission_checker