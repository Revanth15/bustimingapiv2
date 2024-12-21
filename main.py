from fastapi import FastAPI
from routers.database import db_router as db_router 
from routers.busstop import busStops_router as busStops_router 
from routers.users import users_router as users_router 

app = FastAPI()

app.include_router(db_router)
app.include_router(busStops_router)
app.include_router(users_router)

@app.get("/")
async def root():
    return {"message": "Hello World"}