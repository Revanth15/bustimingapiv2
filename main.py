from fastapi import FastAPI
from routers.database import db_router as db_router 

app = FastAPI()

app.include_router(db_router)

@app.get("/")
async def root():
    return {"message": "Hello World"}