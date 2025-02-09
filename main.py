from fastapi import FastAPI
from routers.database import db_router as db_router 
from routers.busstop import busStops_router as busStops_router 
from routers.users import users_router as users_router 
import uvicorn
import os

app = FastAPI()

app.include_router(db_router)
app.include_router(busStops_router)
app.include_router(users_router)

@app.get("/")
async def root():
    return {"message": "Hello World"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)