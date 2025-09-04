import asyncio
from fastapi import FastAPI
from routers.database import db_router as db_router 
from routers.busstop import busStops_router as busStops_router 
from routers.middleware import FirebaseLoggerMiddleware, log_worker
from routers.users import users_router as users_router 
from routers.bus import bus_router as bus_router
from routers.traffic_image import traffic_image_router as traffic_image_router
import uvicorn
import os

app = FastAPI()

app.include_router(db_router)
app.include_router(busStops_router)
app.include_router(users_router)
app.include_router(bus_router)
app.include_router(traffic_image_router)
app.add_middleware(FirebaseLoggerMiddleware)

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(log_worker())

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)