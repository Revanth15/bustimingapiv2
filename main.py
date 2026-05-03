from fastapi import FastAPI
import psutil
from routers.axiomMiddleware import AxiomLoggerMiddleware
from routers.client import lifespan
from routers.database import db_router as db_router, ensure_valid_session
from routers.busstop import busStops_router as busStops_router 
from routers.middleware import FirebaseLoggerMiddleware
from routers.users import users_router as users_router 
from routers.bus import bus_router as bus_router
from routers.car import car_related_router as car_related_router
from routers.mrt import MRT_router as MRT_router
from routers.device_token import device_token_router as device_token_router
from routers.feedback import feedback_router as feedback_router
from routers.directions import directions_router as directions_router
import uvicorn
import os

app = FastAPI(lifespan=lifespan)

app.include_router(db_router)
app.include_router(busStops_router)
app.include_router(users_router)
app.include_router(bus_router)
app.include_router(car_related_router)
app.include_router(MRT_router)
app.include_router(device_token_router)
app.include_router(feedback_router)
app.include_router(directions_router)
# app.add_middleware(FirebaseLoggerMiddleware, exclude_paths=['/bustiming'])
app.add_middleware(
    FirebaseLoggerMiddleware,
    exclude_prefixes=[
        "/bustiming",
        "/health",
        "/favicon.ico",
        "/transit_route",
        "/memory"
    ],
    exclude_exact=[
        "/",  # only root is excluded
    ],
)

app.add_middleware(
    AxiomLoggerMiddleware,
    exclude_prefixes=[
        "/favicon.ico",
        "/health",
        "/transit_route",
        "/memory"
    ],
    exclude_exact=[
        "/",
    ],
)


@app.middleware("http")
async def refresh_supabase_session(request, call_next):
    ensure_valid_session()
    response = await call_next(request)
    return response

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.on_event("shutdown")
async def shutdown_event():
    await AxiomLoggerMiddleware.shutdown()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)

@app.get("/memory")
def memory():
    process = psutil.Process(os.getpid())
    mem = process.memory_info()

    return {
        "rss_mb": round(mem.rss / 1024 / 1024, 2),   # actual RAM used
        "vms_mb": round(mem.vms / 1024 / 1024, 2),   # virtual memory
    }