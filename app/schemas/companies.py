from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, EmailStr

class CompanyBase(BaseModel):
    name: str
    schema_name: str

class CompanyCreate(CompanyBase):
    admin_email: EmailStr     # who will be the first admin user
    admin_username: str

class CompanyResponse(CompanyBase):
    id: UUID
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True