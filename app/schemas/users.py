from uuid import UUID
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr, ConfigDict, field_validator, model_validator

class UserBase(BaseModel):
    username: str
    email: EmailStr

class UserCreate(UserBase):
    role_id: int
    company_id: Optional[UUID] = None  # only required when superadmin calls
    # no password, no company_id
    # password comes from the email flow
    # company_id comes from the admin's token

    model_config = ConfigDict(
        json_schema_extra = {
            "example": {
                "username": "johndoe",
                "email": "johndoe@empresa.com"
            }
        }
    )

class UserResponse(UserBase):
    id: UUID
    role_id: int
    role_name: str = ""
    company_id: Optional[UUID] = None
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @model_validator(mode="before")
    @classmethod
    def extract_role_name(cls, v):
        if hasattr(v, "role") and v.role:
            v.__dict__["role_name"] = v.role.name
        return v

class UserLogin(BaseModel):
    email: EmailStr
    password: str

    model_config = ConfigDict(
        json_schema_extra = {
            "example": {
                "email": "admin@empresa.com",
                "password": "Password123!"
            }
        }
    )

class PasswordSet(BaseModel):
    token: str        # from the email link
    new_password: str

    model_config = ConfigDict(
        json_schema_extra = {
            "example": {
                "token": "12345",
                "new_password": "NewPassword123!"
            }
        }
    )


class PasswordReset(BaseModel):
    token: str
    new_password: str

    model_config = ConfigDict(
        json_schema_extra = {
            "example": {
                "token": "12345",
                "new_password": "NewPassword123!"
            }
        }
    )

class EmailRequest(BaseModel):
    email: EmailStr

    model_config = ConfigDict(
        json_schema_extra = {
            "example": {
                "email": "admin@empresa.com"
            }
        }
    )

class UserUpdate(BaseModel):
    username: Optional[str] = None
    role_id: Optional[int] = None

class UserStatusUpdate(BaseModel):
    is_active: bool