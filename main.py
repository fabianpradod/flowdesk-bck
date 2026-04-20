from fastapi import FastAPI
from app.db.init_db import init_db
from app.api.v1.routes.auth import router as auth_router
from app.api.v1.routes.inventory import router as inventory_router

app = FastAPI()
init_db()

app.include_router(auth_router)
app.include_router(inventory_router)

@app.get("/")
def read_root():
    return {"message": "Flowdesk API"}
