from dotenv import load_dotenv 
import asyncio
import uuid
import datetime
from fastapi import FastAPI, Request
import httpx

load_dotenv()

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
                    "ip": request.client.host,
                    "status_code": message["status"],
                    "user_agent": request.headers.get("user-agent"),
                }
                asyncio.create_task(self._send_log(log_data))
            await send(message)

        await self.app(scope, receive, send_wrapper)

    async def _send_log(self, log_data: dict):
        try:
            async with httpx.AsyncClient(timeout=2) as client:
                await client.post(LOG_ENDPOINT, json=log_data)
        except Exception:
            # Fail silently
            pass