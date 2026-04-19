from functools import lru_cache

from sqlalchemy import Table

from app.models.users import User
from app.tenancy.bootstrap import build_tenant_metadata
from app.utils.exceptions import AppError


@lru_cache(maxsize=128)
def get_tenant_tables(schema_name: str) -> dict[str, Table]:
    metadata = build_tenant_metadata(schema_name)
    return {
        table.name: table
        for table in metadata.tables.values()
        if table.schema == schema_name
    }


def get_user_schema_name(current_user: User) -> str:
    company = current_user.company
    if not current_user.company_id or company is None:
        raise AppError(status_code=403, message="This user is not assigned to a tenant company")
    if not company.is_active:
        raise AppError(status_code=403, message="Company is inactive")
    if not company.schema_name:
        raise AppError(status_code=500, message="Company tenant schema is not configured")
    return company.schema_name
