from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, EmailStr

class UserBase(BaseModel):
    username: str
    email: EmailStr

class UserCreate(UserBase):
    role: str
    # no password, no company_id
    # password comes from the email flow
    # company_id comes from the admin's token

class UserResponse(UserBase):
    id: UUID
    role: str
    company_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class PasswordSet(BaseModel):
    token: str        # from the email link
    new_password: str