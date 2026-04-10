from fastapi import FastAPI
from app.db.init_db import init_db

app = FastAPI()
init_db()

@app.get("/")
def read_root():
    return {"message": "Flowdesk API"}