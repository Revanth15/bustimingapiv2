import os
import httpx
from contextlib import asynccontextmanager
from fastapi import FastAPI

# Global persistent client
_client: httpx.AsyncClient = None

def get_client() -> httpx.AsyncClient:
    return _client

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _client
    _client = httpx.AsyncClient(
        timeout=httpx.Timeout(
            connect=2.0,
            read=5.0,
            write=2.0,
            pool=5.0
        ),
        limits=httpx.Limits(
            max_keepalive_connections=100,
            max_connections=300,
            keepalive_expiry=30
        ),
        headers={'AccountKey': os.getenv("ACCOUNT_KEY")},
        http2=True
    )
    yield
    await _client.aclose()