from pydantic import BaseModel

class PermissionBase(BaseModel):
    name: str

class PermissionResponse(PermissionBase):
    id: int

    class Config:
        orm_mode = True