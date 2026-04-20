from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr

class CompanyBase(BaseModel):
    name: str

class CompanyCreate(CompanyBase):
    admin_email: EmailStr     # who will be the first admin user
    admin_username: str

class CompanyResponse(CompanyBase):
    id: UUID
    schema_name: str
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
