import uuid
import datetime
import time
import asyncio
from fastapi import Request
import httpx
from routers.utils import getEnvVariable

class AxiomLoggerMiddleware:
    def __init__(self, app, exclude_prefixes=None):
        self.app = app
        self.exclude_prefixes = tuple(exclude_prefixes or [])
    
    def _should_log(self, path: str) -> bool:
        return not path.startswith(self.exclude_prefixes)
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        
        request = Request(scope, receive=receive)
        start = time.perf_counter()
        
        async def send_wrapper(message):
            if (
                message["type"] == "http.response.start"
                # and self._should_log(request.url.path)
            ):
                duration_ms = (time.perf_counter() - start) * 1000
                log_data = {
                    "id": str(uuid.uuid4()),
                    "timestamp": datetime.datetime.utcnow().isoformat(),
                    "method": request.method,
                    "path": request.url.path,
                    "status": message["status"],
                    "duration_ms": round(duration_ms, 2),
                    "ip": request.client.host if request.client else None,
                    "user_agent": request.headers.get("user-agent"),
                    "params": dict(request.query_params),
                }
                # Fire and forget
                asyncio.create_task(send_log(log_data))
            
            await send(message)
        
        await self.app(scope, receive, send_wrapper)

AXIOM_TOKEN = getEnvVariable("AXIOM_TOKEN")
AXIOM_DATASET = getEnvVariable("AXIOM_DATASET")
AXIOM_INGEST_URL = f"https://api.axiom.co/v1/datasets/{AXIOM_DATASET}/ingest"

async def send_log(log: dict):
    try:
        payload = {
            **log,
            "_time": time.time(),
        }
        async with httpx.AsyncClient(timeout=0.5) as client:
            await client.post(
                AXIOM_INGEST_URL,
                json=[payload],
                headers={
                    "Authorization": f"Bearer {AXIOM_TOKEN}",
                    "Content-Type": "application/json",
                },
            )
    except Exception:
        pass  # Fail silently