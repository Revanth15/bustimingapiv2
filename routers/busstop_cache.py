import asyncio
import time
from typing import Any, Awaitable, Callable


class CacheEntry:
    __slots__ = ("value", "expires_at")

    def __init__(self, value: Any, ttl: float):
        self.value = value
        self.expires_at = time.monotonic() + ttl

    def is_expired(self) -> bool:
        return time.monotonic() > self.expires_at


class BusStopCache:
    def __init__(self, ttl: float = 8.0, maxsize: int = 500):
        self.ttl = ttl
        self.maxsize = maxsize
        self._store: dict[str, CacheEntry] = {}
        self._inflight: dict[str, asyncio.Future[Any]] = {}
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [key for key, value in self._store.items() if now > value.expires_at]
        for key in expired:
            del self._store[key]

    def _enforce_capacity(self) -> None:
        if len(self._store) < self.maxsize:
            return
        self._evict_expired()
        if len(self._store) < self.maxsize:
            return
        oldest = next(iter(self._store), None)
        if oldest is not None:
            del self._store[oldest]

    async def get_or_fetch(
        self,
        key: str,
        fetch_fn: Callable[[], Awaitable[Any]],
    ) -> Any:
        entry = self._store.get(key)
        if entry and not entry.is_expired():
            return entry.value

        async with self._lock:
            entry = self._store.get(key)
            if entry and not entry.is_expired():
                return entry.value

            future = self._inflight.get(key)
            if future is None:
                loop = asyncio.get_running_loop()
                future = loop.create_future()
                self._inflight[key] = future
                self._enforce_capacity()

                task = loop.create_task(self._resolve_inflight(key, future, fetch_fn))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

        return await asyncio.shield(future)

    async def _resolve_inflight(
        self,
        key: str,
        future: asyncio.Future[Any],
        fetch_fn: Callable[[], Awaitable[Any]],
    ) -> None:
        try:
            result = await fetch_fn()
        except asyncio.CancelledError:
            await self._clear_inflight(key, future)
            if not future.done():
                future.cancel()
            raise
        except Exception as exc:
            await self._clear_inflight(key, future)
            if not future.done():
                future.set_exception(exc)
            return

        async with self._lock:
            if self._inflight.get(key) is future:
                self._store[key] = CacheEntry(result, self.ttl)
                self._inflight.pop(key, None)

        if not future.done():
            future.set_result(result)

    async def _clear_inflight(self, key: str, future: asyncio.Future[Any]) -> None:
        async with self._lock:
            if self._inflight.get(key) is future:
                self._inflight.pop(key, None)
