import json
import os
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore
import asyncio
import uuid
import datetime
from fastapi import FastAPI, Request

load_dotenv()

firebase_json = os.environ["FIREBASE_CREDENTIALS"]
cred_dict = json.loads(firebase_json)
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)

db = firestore.client()

log_queue = asyncio.Queue()

async def log_worker():
    while True:
        log_data = await log_queue.get()
        try:
            db.collection("logs").add(log_data)
        except Exception as e:
            print("Log write failed:", e)
        finally:
            log_queue.task_done()

# --- Middleware ---
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
                }
                # Fire-and-forget: push into queue
                asyncio.create_task(log_queue.put(log_data))
            await send(message)

        await self.app(scope, receive, send_wrapper)