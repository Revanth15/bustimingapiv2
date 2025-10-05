import uuid
import datetime
import threading
from fastapi import FastAPI, Request
import httpx

LOG_ENDPOINT = "https://bussinganalytics.vercel.app/api/log"

class FirebaseLoggerMiddleware:
    def __init__(self, app: FastAPI):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                log_data = {
                    "id": str(uuid.uuid4()),
                    "timestamp": datetime.datetime.utcnow().isoformat(),
                    "method": request.method,
                    "path": request.url.path,
                    "ip": request.client.host if request.client else None,
                    "status_code": message["status"],
                    "user_agent": request.headers.get("user-agent"),
                    "params": dict(request.query_params),
                    "route_path": getattr(request.scope.get("route"), "path", None)
                }
                # Fire-and-forget logging
                threading.Thread(target=self._send_log, args=(log_data,), daemon=True).start()

            await send(message)

        await self.app(scope, receive, send_wrapper)

    def _send_log(self, log_data: dict):
        try:
            httpx.post(LOG_ENDPOINT, json=log_data, timeout=0.5)
        except Exception:
            # Fail silently
            pass