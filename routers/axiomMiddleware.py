import uuid
import datetime
import time
import threading
from fastapi import FastAPI, Request
import httpx
from routers.utils import getEnvVariable

AXIOM_TOKEN = getEnvVariable("AXIOM_TOKEN")
AXIOM_DATASET = getEnvVariable("AXIOM_DATASET")
AXIOM_INGEST_URL = f"https://api.axiom.co/v1/datasets/{AXIOM_DATASET}/ingest"

class AxiomLoggerMiddleware:
    def __init__(self, app: FastAPI, exclude_prefixes: list[str] | None = None):
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
                and self._should_log(request.url.path)
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
                threading.Thread(
                    target=self._send_log,
                    args=(log_data,),
                    daemon=True
                ).start()
            
            await send(message)
        
        await self.app(scope, receive, send_wrapper)
    
    def _send_log(self, log_data: dict):
        try:
            httpx.post(
                AXIOM_INGEST_URL,
                json=[log_data],
                headers={
                    "Authorization": f"Bearer {AXIOM_TOKEN}",
                    "Content-Type": "application/json",
                },
                timeout=0.5
            )
        except Exception:
            # Fail silently
            pass