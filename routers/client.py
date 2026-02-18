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
            connect=2.0,   # fail fast if LTA unreachable
            read=5.0,      # LTA is 50ms, 5s is generous
            write=2.0,
            pool=2.0
        ),
        limits=httpx.Limits(
            max_keepalive_connections=20,  # reuse up to 20 connections
            max_connections=50,            # hard cap
            keepalive_expiry=30            # keep connections alive 30s
        ),
        headers={'AccountKey': os.getenv("ACCOUNT_KEY")},  # set once, reused forever
        http2=True  # HTTP/2 multiplexing if LTA supports it
    )
    yield
    await _client.aclose()