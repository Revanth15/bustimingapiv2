from __future__ import annotations

import asyncio
import gzip
import hashlib
import inspect
import json
import logging
import os
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlencode

from fastapi import Request, Response
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

logger = logging.getLogger(__name__)


class DiskBlobCache:
    """
    Stores large JSON responses as gzipped blobs on disk and serves them directly.
    Metadata is kept in a small sidecar JSON file so cache hits avoid loading the
    original payload back into memory.
    """

    def __init__(
        self,
        cache_dir: str | Path,
        max_disk_usage_bytes: int,
        cleanup_interval_seconds: int,
        content_type: str = "application/json",
        content_encoding: str = "gzip",
        compresslevel: int = 6,
        lock_wait_seconds: float = 10.0,
        stale_lock_seconds: float = 120.0,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_disk_usage_bytes = max_disk_usage_bytes
        self.cleanup_interval_seconds = cleanup_interval_seconds
        self.content_type = content_type
        self.content_encoding = content_encoding
        self.compresslevel = compresslevel
        self.lock_wait_seconds = lock_wait_seconds
        self.stale_lock_seconds = stale_lock_seconds
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()
        self._cleanup_guard = asyncio.Lock()
        self._last_cleanup_at = 0.0

    async def get_cached_or_generate(
        self,
        request: Request,
        route_key: str,
        ttl_seconds: int,
        generator: Callable[[], Awaitable[Any] | Any],
        status_code: int = 200,
    ) -> Response:
        request_key = self.build_request_key(route_key, request)
        cache_id = self._cache_id(request_key)

        cached = self._build_cached_response(
            request=request,
            cache_id=cache_id,
            status_code=status_code,
        )
        if cached is not None:
            self._schedule_cleanup()
            return cached

        async with await self._get_lock(cache_id):
            cached = self._build_cached_response(
                request=request,
                cache_id=cache_id,
                status_code=status_code,
            )
            if cached is not None:
                self._schedule_cleanup()
                return cached

            lock_path = self._lock_path(cache_id)
            file_lock_acquired = await asyncio.to_thread(self._acquire_file_lock, lock_path)

            if not file_lock_acquired:
                logger.warning("blob-cache lock timeout for key=%s", request_key)
                cached = self._build_cached_response(
                    request=request,
                    cache_id=cache_id,
                    status_code=status_code,
                )
                if cached is not None:
                    self._schedule_cleanup()
                    return cached

                return await self._generate_live_response(
                    request=request,
                    route_key=route_key,
                    request_key=request_key,
                    ttl_seconds=ttl_seconds,
                    generator=generator,
                    status_code=status_code,
                    cache_id=cache_id,
                    x_cache="MISS-LOCK-BYPASS",
                )

            try:
                cached = self._build_cached_response(
                    request=request,
                    cache_id=cache_id,
                    status_code=status_code,
                )
                if cached is not None:
                    self._schedule_cleanup()
                    return cached

                response = await self._generate_and_store(
                    request=request,
                    route_key=route_key,
                    request_key=request_key,
                    ttl_seconds=ttl_seconds,
                    generator=generator,
                    status_code=status_code,
                    cache_id=cache_id,
                )
                self._schedule_cleanup()
                return response
            finally:
                await asyncio.to_thread(self._release_file_lock, lock_path)

    def delete(self, key: str) -> int:
        deleted = 0
        for meta_path in self.cache_dir.glob("*.meta.json"):
            metadata = self._read_metadata(meta_path)
            if not metadata:
                continue
            if key in {
                metadata.get("route_key"),
                metadata.get("request_key"),
                meta_path.stem.replace(".meta", ""),
            }:
                deleted += self._delete_entry(meta_path, metadata, reason="manual_purge")
        return deleted

    def clear(self) -> int:
        deleted = 0
        for meta_path in self.cache_dir.glob("*.meta.json"):
            metadata = self._read_metadata(meta_path)
            deleted += self._delete_entry(meta_path, metadata, reason="clear")
        for blob_path in self.cache_dir.glob("*.blob.gz"):
            if blob_path.exists():
                blob_path.unlink(missing_ok=True)
                deleted += 1
        for lock_path in self.cache_dir.glob("*.lock"):
            if lock_path.exists():
                lock_path.unlink(missing_ok=True)
                deleted += 1
        return deleted

    async def cleanup(self) -> None:
        await asyncio.to_thread(self._cleanup_sync)

    def build_request_key(self, route_key: str, request: Request) -> str:
        if not request.query_params:
            return route_key

        stable_items = sorted(request.query_params.multi_items(), key=lambda item: (item[0], item[1]))
        query_string = urlencode(stable_items, doseq=True)
        return f"{route_key}?{query_string}"

    def _cache_id(self, request_key: str) -> str:
        return hashlib.sha256(request_key.encode("utf-8")).hexdigest()

    def _meta_path(self, cache_id: str) -> Path:
        return self.cache_dir / f"{cache_id}.meta.json"

    def _lock_path(self, cache_id: str) -> Path:
        return self.cache_dir / f"{cache_id}.lock"

    async def _get_lock(self, cache_id: str) -> asyncio.Lock:
        async with self._locks_guard:
            lock = self._locks.get(cache_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[cache_id] = lock
            return lock

    def _build_cached_response(
        self,
        request: Request,
        cache_id: str,
        status_code: int,
    ) -> Response | None:
        meta_path = self._meta_path(cache_id)
        metadata = self._read_metadata(meta_path)
        if not metadata:
            return None

        blob_name = metadata.get("blob_name")
        if not blob_name:
            logger.warning("blob-cache metadata missing blob_name key=%s", metadata.get("request_key"))
            self._delete_entry(meta_path, metadata, reason="invalid_metadata")
            return None

        blob_path = self.cache_dir / blob_name
        if not blob_path.exists():
            logger.warning("blob-cache blob missing key=%s blob=%s", metadata.get("request_key"), blob_name)
            self._delete_entry(meta_path, metadata, reason="missing_blob")
            return None

        now = time.time()
        expires_at = float(metadata.get("expires_at_ts", 0))
        if expires_at <= now:
            logger.info("blob-cache expired key=%s", metadata.get("request_key"))
            self._delete_entry(meta_path, metadata, reason="expired")
            return None

        headers = self._response_headers(metadata, ttl_seconds=max(0, int(expires_at - now)), x_cache="HIT")
        etag = metadata.get("etag")
        if etag and request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers=headers)

        self._touch(blob_path)
        self._touch(meta_path)
        logger.info("blob-cache hit key=%s", metadata.get("request_key"))
        return FileResponse(
            path=blob_path,
            media_type=metadata.get("content_type", self.content_type),
            status_code=status_code,
            headers=headers,
        )

    async def _generate_and_store(
        self,
        request: Request,
        route_key: str,
        request_key: str,
        ttl_seconds: int,
        generator: Callable[[], Awaitable[Any] | Any],
        status_code: int,
        cache_id: str,
    ) -> Response:
        try:
            payload = generator()
            if inspect.isawaitable(payload):
                payload = await payload
        except Exception:
            logger.exception("blob-cache generation failed key=%s", request_key)
            raise

        created_at = datetime.now(timezone.utc)
        expires_at = created_at.timestamp() + ttl_seconds
        blob_name = f"{cache_id}.{int(created_at.timestamp())}.{uuid.uuid4().hex}.blob.gz"
        blob_path = self.cache_dir / blob_name

        try:
            etag, uncompressed_size = await asyncio.to_thread(self._write_gzipped_payload, payload, blob_path)
            compressed_size = blob_path.stat().st_size
            metadata = {
                "cache_version": 1,
                "route_key": route_key,
                "request_key": request_key,
                "blob_name": blob_name,
                "created_at": created_at.isoformat(),
                "created_at_ts": created_at.timestamp(),
                "expires_at": datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat(),
                "expires_at_ts": expires_at,
                "content_type": self.content_type,
                "content_encoding": self.content_encoding,
                "etag": etag,
                "uncompressed_size": uncompressed_size,
                "compressed_size": compressed_size,
            }

            previous = self._read_metadata(self._meta_path(cache_id))
            temp_meta_path = await asyncio.to_thread(self._write_temp_metadata, cache_id, metadata)
            # The blob file is already complete here. Swapping the small metadata file is
            # the atomic step that makes the new cache entry visible to readers.
            os.replace(temp_meta_path, self._meta_path(cache_id))

            if previous and previous.get("blob_name") and previous["blob_name"] != blob_name:
                self._safe_unlink(self.cache_dir / previous["blob_name"])

            self._touch(blob_path)
            self._touch(self._meta_path(cache_id))
            logger.info("blob-cache write key=%s size=%s", request_key, compressed_size)

            headers = self._response_headers(metadata, ttl_seconds=ttl_seconds, x_cache="MISS")
            if metadata["etag"] and request.headers.get("if-none-match") == metadata["etag"]:
                return Response(status_code=304, headers=headers)

            return FileResponse(
                path=blob_path,
                media_type=self.content_type,
                status_code=status_code,
                headers=headers,
            )
        except Exception:
            logger.exception("blob-cache write failed key=%s", request_key)
            self._safe_unlink(blob_path)
            return await self._build_uncached_live_response(
                payload=payload,
                request=request,
                route_key=route_key,
                request_key=request_key,
                ttl_seconds=ttl_seconds,
                status_code=status_code,
                cache_id=cache_id,
                x_cache="MISS-WRITE-ERROR",
            )

    async def _generate_live_response(
        self,
        request: Request,
        route_key: str,
        request_key: str,
        ttl_seconds: int,
        generator: Callable[[], Awaitable[Any] | Any],
        status_code: int,
        cache_id: str,
        x_cache: str,
    ) -> Response:
        try:
            payload = generator()
            if inspect.isawaitable(payload):
                payload = await payload
        except Exception:
            logger.exception("blob-cache generation failed key=%s", request_key)
            raise

        return await self._build_uncached_live_response(
            payload=payload,
            request=request,
            route_key=route_key,
            request_key=request_key,
            ttl_seconds=ttl_seconds,
            status_code=status_code,
            cache_id=cache_id,
            x_cache=x_cache,
        )

    async def _build_uncached_live_response(
        self,
        payload: Any,
        request: Request,
        route_key: str,
        request_key: str,
        ttl_seconds: int,
        status_code: int,
        cache_id: str,
        x_cache: str,
    ) -> Response:
        created_at = datetime.now(timezone.utc)
        temp_blob = self.cache_dir / f"{cache_id}.{uuid.uuid4().hex}.live.blob.gz"
        etag, uncompressed_size = await asyncio.to_thread(self._write_gzipped_payload, payload, temp_blob)
        metadata = {
            "route_key": route_key,
            "request_key": request_key,
            "created_at": created_at.isoformat(),
            "expires_at": datetime.fromtimestamp(created_at.timestamp() + ttl_seconds, tz=timezone.utc).isoformat(),
            "content_type": self.content_type,
            "content_encoding": self.content_encoding,
            "etag": etag,
            "uncompressed_size": uncompressed_size,
            "compressed_size": temp_blob.stat().st_size,
        }
        headers = self._response_headers(metadata, ttl_seconds=ttl_seconds, x_cache=x_cache)
        if etag and request.headers.get("if-none-match") == etag:
            self._safe_unlink(temp_blob)
            return Response(status_code=304, headers=headers)

        return FileResponse(
            path=temp_blob,
            media_type=self.content_type,
            status_code=status_code,
            headers=headers,
            background=BackgroundTask(self._safe_unlink, temp_blob),
        )

    def _response_headers(self, metadata: dict[str, Any], ttl_seconds: int, x_cache: str) -> dict[str, str]:
        return {
            "Cache-Control": f"public, max-age=60, s-maxage={max(0, ttl_seconds)}, stale-while-revalidate=60",
            "Content-Encoding": metadata.get("content_encoding", self.content_encoding),
            "ETag": metadata.get("etag", ""),
            "Vary": "Accept-Encoding",
            "X-Cache": x_cache,
            "X-Cache-Key": metadata.get("request_key", ""),
            "X-Compressed-Bytes": str(metadata.get("compressed_size", "")),
            "X-Uncompressed-Bytes": str(metadata.get("uncompressed_size", "")),
        }

    def _write_gzipped_payload(self, payload: Any, blob_path: Path) -> tuple[str, int]:
        encoder = json.JSONEncoder(separators=(",", ":"), ensure_ascii=False)
        hasher = hashlib.sha256()
        uncompressed_size = 0

        with open(blob_path, "wb") as raw_file:
            with gzip.GzipFile(
                fileobj=raw_file,
                mode="wb",
                compresslevel=self.compresslevel,
                mtime=0,
            ) as gzip_file:
                if isinstance(payload, (bytes, bytearray, memoryview)):
                    chunk = bytes(payload)
                    hasher.update(chunk)
                    uncompressed_size += len(chunk)
                    gzip_file.write(chunk)
                elif isinstance(payload, str):
                    chunk = payload.encode("utf-8")
                    hasher.update(chunk)
                    uncompressed_size += len(chunk)
                    gzip_file.write(chunk)
                else:
                    for piece in encoder.iterencode(payload):
                        chunk = piece.encode("utf-8")
                        hasher.update(chunk)
                        uncompressed_size += len(chunk)
                        gzip_file.write(chunk)

        return f"\"{hasher.hexdigest()}\"", uncompressed_size

    def _write_temp_metadata(self, cache_id: str, metadata: dict[str, Any]) -> str:
        fd, temp_path = tempfile.mkstemp(prefix=f"{cache_id}.", suffix=".meta.tmp", dir=self.cache_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(metadata, handle, separators=(",", ":"))
            return temp_path
        except Exception:
            os.unlink(temp_path)
            raise

    def _read_metadata(self, meta_path: Path) -> dict[str, Any] | None:
        if not meta_path.exists():
            return None

        try:
            with open(meta_path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception:
            logger.exception("blob-cache metadata read failed path=%s", meta_path)
            self._safe_unlink(meta_path)
            return None

    def _delete_entry(self, meta_path: Path, metadata: dict[str, Any] | None, reason: str) -> int:
        deleted = 0
        blob_name = metadata.get("blob_name") if metadata else None
        if blob_name:
            blob_path = self.cache_dir / blob_name
            if blob_path.exists():
                blob_path.unlink(missing_ok=True)
                deleted += 1
        if meta_path.exists():
            meta_path.unlink(missing_ok=True)
            deleted += 1
        logger.info("blob-cache eviction reason=%s meta=%s", reason, meta_path.name)
        return deleted

    def _touch(self, path: Path) -> None:
        try:
            os.utime(path, None)
        except FileNotFoundError:
            return
        except Exception:
            logger.debug("blob-cache touch failed path=%s", path, exc_info=True)

    def _schedule_cleanup(self) -> None:
        if time.monotonic() - self._last_cleanup_at < self.cleanup_interval_seconds:
            return
        self._last_cleanup_at = time.monotonic()
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._run_cleanup())
        except RuntimeError:
            self._cleanup_sync()

    async def _run_cleanup(self) -> None:
        if self._cleanup_guard.locked():
            return
        async with self._cleanup_guard:
            await asyncio.to_thread(self._cleanup_sync)

    def _cleanup_sync(self) -> None:
        referenced_blobs: set[str] = set()
        active_entries: list[tuple[float, int, Path, dict[str, Any]]] = []
        total_size = 0
        now = time.time()

        for meta_path in self.cache_dir.glob("*.meta.json"):
            metadata = self._read_metadata(meta_path)
            if not metadata:
                continue

            blob_name = metadata.get("blob_name")
            if not blob_name:
                self._delete_entry(meta_path, metadata, reason="invalid_metadata")
                continue

            blob_path = self.cache_dir / blob_name
            if not blob_path.exists():
                self._delete_entry(meta_path, metadata, reason="missing_blob")
                continue

            referenced_blobs.add(blob_name)
            expires_at = float(metadata.get("expires_at_ts", 0))
            if expires_at <= now:
                self._delete_entry(meta_path, metadata, reason="expired")
                continue

            try:
                blob_stat = blob_path.stat()
                meta_stat = meta_path.stat()
            except FileNotFoundError:
                continue

            last_access = max(blob_stat.st_atime, meta_stat.st_atime)
            size = blob_stat.st_size
            total_size += size
            active_entries.append((last_access, size, meta_path, metadata))

        for blob_path in self.cache_dir.glob("*.blob.gz"):
            try:
                blob_mtime = blob_path.stat().st_mtime
            except FileNotFoundError:
                continue
            if blob_path.name not in referenced_blobs and now - blob_mtime > self.stale_lock_seconds:
                blob_path.unlink(missing_ok=True)
                logger.info("blob-cache eviction reason=orphan_blob blob=%s", blob_path.name)

        if total_size <= self.max_disk_usage_bytes:
            return

        active_entries.sort(key=lambda item: item[0])
        for _, size, meta_path, metadata in active_entries:
            if total_size <= self.max_disk_usage_bytes:
                break
            total_size -= size
            self._delete_entry(meta_path, metadata, reason="size_limit")

    def _acquire_file_lock(self, lock_path: Path) -> bool:
        deadline = time.monotonic() + self.lock_wait_seconds
        while True:
            try:
                # O_EXCL keeps cross-process builders from regenerating the same cache key.
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(f"{os.getpid()} {time.time()}\n")
                return True
            except FileExistsError:
                try:
                    age = time.time() - lock_path.stat().st_mtime
                    if age > self.stale_lock_seconds:
                        lock_path.unlink(missing_ok=True)
                        logger.warning("blob-cache removed stale lock path=%s", lock_path.name)
                        continue
                except FileNotFoundError:
                    continue

                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.1)

    def _release_file_lock(self, lock_path: Path) -> None:
        self._safe_unlink(lock_path)

    def _safe_unlink(self, path: str | Path) -> None:
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            logger.debug("blob-cache unlink failed path=%s", path, exc_info=True)
