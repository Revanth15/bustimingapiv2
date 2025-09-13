import asyncio
from fastapi import FastAPI
from routers.database import db_router as db_router 
from routers.busstop import busStops_router as busStops_router 
from routers.middleware import FirebaseLoggerMiddleware
from routers.users import users_router as users_router 
from routers.bus import bus_router as bus_router
from routers.traffic_image import traffic_image_router as traffic_image_router
from routers.mrt import MRT_router as MRT_router
import uvicorn
import os

app = FastAPI()

app.include_router(db_router)
app.include_router(busStops_router)
app.include_router(users_router)
app.include_router(bus_router)
app.include_router(traffic_image_router)
app.include_router(MRT_router)
app.add_middleware(FirebaseLoggerMiddleware)

@app.get("/")
async def root():
    return {"message": "Hello World"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)