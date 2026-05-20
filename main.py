from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.db.init_db import init_db
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.users import router as users_router
from app.api.v1.routes.roles import router as roles_router
from app.api.v1.routes.inventory import router as inventory_router
from app.utils.exceptions import build_error_payload

app = FastAPI()
init_db()


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request: Request, exc: StarletteHTTPException):
    payload = build_error_payload(exc)
    return JSONResponse(status_code=exc.status_code, content=payload)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "message": "Invalid request format",
            "code": "validation_error",
            "errors": exc.errors(),
        },
    )

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(roles_router)
app.include_router(inventory_router)

@app.get("/")
def read_root():
    return {"message": "Flowdesk API"}
