from __future__ import annotations

import asyncio
import json
import re
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote

import httpx
import pytz
from fastapi import HTTPException

from routers.client import get_client
from routers.utils import DEFAULT_BUS, emit_exception_log, service_sort_key

NUS_NEXTBUS_BASE_URL = "https://bus.hewliyang.com"
NUS_STOPS_URL = (
    "https://raw.githubusercontent.com/hewliyang/nus-nextbus-web/main/"
    "src/lib/data/stops.json"
)
NUS_ROUTES_URL = (
    "https://raw.githubusercontent.com/hewliyang/nus-nextbus-web/main/"
    "src/lib/data/routes.json"
)
NUS_BUS_STATIC_KEY = "nusBusStatic"
BUS_STOP_AVAILABLE_SERVICES_KEY = "busStopAvailableServices"
NUS_ROUTE_CODES_KEY = "routes"
NUS_STOP_CODES_KEY = "stops"
NUS_STATIC_CACHE_SECONDS = 30 * 60
NUS_TIMING_CACHE_SECONDS = 8.0
NUS_OPERATOR = "NUS"
NUS_ROAD_NAME = "NUS"

_NUS_STOP_CODE_RE = re.compile(r"^[A-Za-z0-9-]+$")
_INT_RE = re.compile(r"\d+")


@dataclass
class CacheEntry:
    expires_at: float
    value: Any


_static_cache: CacheEntry | None = None
_timing_cache: dict[str, CacheEntry] = {}
_timing_locks: dict[str, asyncio.Lock] = {}


class _BusTimingTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._in_row = False
        self._in_cell = False
        self._current_row: list[str] = []
        self._current_cell: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._in_row = True
            self._current_row = []
        elif self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._current_cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            text = " ".join(" ".join(self._current_cell).split())
            self._current_row.append(text)
            self._current_cell = []
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            if self._current_row:
                self.rows.append(self._current_row)
            self._current_row = []
            self._in_row = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            text = " ".join(data.split())
            if text:
                self._current_cell.append(text)


async def _get_json(url: str) -> Any:
    client = get_client()
    if client is not None:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()

    async with httpx.AsyncClient(timeout=10.0, http2=True) as fallback_client:
        response = await fallback_client.get(url)
        response.raise_for_status()
        return response.json()


async def _get_text(url: str) -> str:
    client = get_client()
    if client is not None:
        response = await client.get(url)
        response.raise_for_status()
        return response.text

    async with httpx.AsyncClient(timeout=10.0, http2=True) as fallback_client:
        response = await fallback_client.get(url)
        response.raise_for_status()
        return response.text


def _parse_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _normalize_stop_code(stop_code: str) -> str:
    return stop_code.strip().upper()


def is_valid_nus_stop_code_shape(stop_code: str) -> bool:
    return bool(stop_code and _NUS_STOP_CODE_RE.fullmatch(stop_code))


def is_lta_stop_code(stop_code: str) -> bool:
    return bool(re.fullmatch(r"\d{5}", stop_code or ""))


async def fetch_nus_static_data() -> dict[str, Any]:
    stops, routes = await asyncio.gather(_get_json(NUS_STOPS_URL), _get_json(NUS_ROUTES_URL))
    return {
        NUS_STOP_CODES_KEY: stops,
        NUS_ROUTE_CODES_KEY: routes,
    }


async def get_nus_static_data(db_client: Any | None = None) -> dict[str, Any]:
    global _static_cache
    now = time.monotonic()
    if _static_cache and _static_cache.expires_at > now:
        return deepcopy(_static_cache.value)

    if db_client is not None:
        response = (
            db_client.table("jsons")
            .select("json_value")
            .eq("id", NUS_BUS_STATIC_KEY)
            .execute()
        )
        if response.data:
            value = _parse_json_value(response.data[0]["json_value"])
            _static_cache = CacheEntry(now + NUS_STATIC_CACHE_SECONDS, value)
            return deepcopy(value)

    value = await fetch_nus_static_data()
    _static_cache = CacheEntry(now + NUS_STATIC_CACHE_SECONDS, value)
    return deepcopy(value)


async def is_nus_stop_code(stop_code: str, db_client: Any | None = None) -> bool:
    if not is_valid_nus_stop_code_shape(stop_code):
        return False
    static_data = await get_nus_static_data(db_client)
    normalized = _normalize_stop_code(stop_code)
    return normalized in get_nus_stop_codes(static_data)


def get_nus_stop_codes(static_data: dict[str, Any]) -> set[str]:
    return {
        _normalize_stop_code(str(stop.get("name", "")))
        for stop in static_data.get(NUS_STOP_CODES_KEY, [])
        if stop.get("name")
    }


def get_nus_route_codes(static_data: dict[str, Any]) -> set[str]:
    return {
        str(route_code)
        for route_code in static_data.get(NUS_ROUTE_CODES_KEY, {}).keys()
    }


def build_nus_stop_services_lookup(static_data: dict[str, Any]) -> dict[str, list[str]]:
    stop_services: dict[str, list[str]] = {}
    for service_no, stops in static_data.get(NUS_ROUTE_CODES_KEY, {}).items():
        for stop in stops:
            stop_code = _normalize_stop_code(str(stop.get("busstopcode", "")))
            if not stop_code:
                continue
            services = stop_services.setdefault(stop_code, [])
            if service_no not in services:
                services.append(service_no)

    for stop_code, services in stop_services.items():
        stop_services[stop_code] = sorted(services, key=service_sort_key)
    return stop_services


def format_nus_bus_stops(static_data: dict[str, Any], modified_at: str) -> list[dict[str, Any]]:
    services_lookup = build_nus_stop_services_lookup(static_data)
    rows = []
    for stop in static_data.get(NUS_STOP_CODES_KEY, []):
        stop_code = _normalize_stop_code(str(stop["name"]))
        rows.append(
            {
                "id": stop_code,
                "description": stop.get("caption") or stop.get("LongName") or stop_code,
                "latitude": float(stop["latitude"]),
                "longitude": float(stop["longitude"]),
                "road_name": NUS_ROAD_NAME,
                "bus_services": ",".join(services_lookup.get(stop_code, [])),
                "modified_at": modified_at,
            }
        )
    return rows


def format_nus_bus_routes(static_data: dict[str, Any], modified_at: str) -> list[dict[str, Any]]:
    rows = []
    for service_no, stops in static_data.get(NUS_ROUTE_CODES_KEY, {}).items():
        ordered_stops = sorted(stops, key=lambda stop: int(stop.get("seq", 0)))
        route_payload = {
            "serviceNo": str(service_no),
            "routes": [
                {
                    "direction": "1",
                    "busStopIDs": [
                        _normalize_stop_code(str(stop.get("busstopcode", "")))
                        for stop in ordered_stops
                        if stop.get("busstopcode")
                    ],
                    "polyline": "",
                }
            ],
        }
        rows.append(
            {
                "id": f"nus-{service_no}",
                "service_no": str(service_no),
                "json_value": json.dumps(route_payload, separators=(",", ":")),
                "modified_at": modified_at,
            }
        )
    return rows


def format_nus_bus_route_raw(static_data: dict[str, Any], modified_at: str) -> list[dict[str, Any]]:
    stop_payloads: dict[str, dict[str, Any]] = {}
    for service_no, stops in static_data.get(NUS_ROUTE_CODES_KEY, {}).items():
        for stop in stops:
            stop_code = _normalize_stop_code(str(stop.get("busstopcode", "")))
            if not stop_code:
                continue
            stop_payload = stop_payloads.setdefault(
                stop_code,
                {
                    "bus_stop_code": stop_code,
                    "services": {},
                },
            )
            service_payload = stop_payload["services"].setdefault(
                str(service_no),
                {
                    "service_no": str(service_no),
                    "operator": NUS_OPERATOR,
                    "directions": {},
                },
            )
            if "1" in service_payload["directions"]:
                continue
            service_payload["directions"]["1"] = {
                "direction": 1,
                "stop_sequence": int(stop.get("seq", 0)),
                "distance": None,
                "schedules": {
                    "weekday": {"first_bus": "-", "last_bus": "-"},
                    "saturday": {"first_bus": "-", "last_bus": "-"},
                    "sunday": {"first_bus": "-", "last_bus": "-"},
                },
            }

    return [
        {
            "id": stop_code,
            "bus_stop_code": stop_code,
            "json_value": json.dumps(payload, separators=(",", ":")),
            "modified_at": modified_at,
        }
        for stop_code, payload in stop_payloads.items()
    ]


def merge_bus_stop_available_services(
    existing: Any,
    nus_lookup: dict[str, list[str]],
) -> dict[str, list[str]]:
    merged = _parse_json_value(existing) if existing else {}
    if not isinstance(merged, dict):
        merged = {}

    for stop_code, services in nus_lookup.items():
        existing_services = merged.get(stop_code, [])
        if isinstance(existing_services, str):
            existing_services = [item for item in existing_services.split(",") if item]
        combined = {str(service) for service in existing_services}
        combined.update(str(service) for service in services)
        merged[stop_code] = sorted(combined, key=service_sort_key)

    return merged


def _parse_arrival_minutes(cell_text: str) -> int:
    text = cell_text.strip()
    if not text or text.startswith("-"):
        return -100
    match = _INT_RE.search(text)
    if not match:
        return -100
    return int(match.group(0))


def _build_nus_bus_detail(minutes: int) -> dict[str, Any]:
    if minutes < 0:
        return DEFAULT_BUS.copy()
    return {
        "busArrivalTime": minutes,
        "busLoad": "-",
        "busFeature": "-",
        "busType": "-",
        "busMonitored": 1,
        "busLongitude": "-",
        "busLatitude": "-",
    }


def parse_nus_timing_html(html: str, route_codes: set[str]) -> list[dict[str, Any]]:
    parser = _BusTimingTableParser()
    parser.feed(html)

    timings: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in parser.rows:
        if len(row) < 3 or row[0].lower() == "route":
            continue
        service_no = row[0].strip()
        if service_no not in route_codes or service_no in seen:
            continue

        first_arrival = _parse_arrival_minutes(row[1])
        second_arrival = _parse_arrival_minutes(row[2])
        timings.append(
            {
                "serviceNo": service_no,
                "serviceDetails": [
                    _build_nus_bus_detail(first_arrival),
                    _build_nus_bus_detail(second_arrival),
                    DEFAULT_BUS.copy(),
                ],
            }
        )
        seen.add(service_no)

    return sorted(timings, key=lambda item: service_sort_key(item["serviceNo"]))


async def fetch_nus_timings(
    stop_code: str,
    requested_services: set[str],
    process_all: bool,
    db_client: Any | None = None,
) -> list[dict[str, Any]]:
    normalized_stop_code = _normalize_stop_code(stop_code)
    cache_key = normalized_stop_code
    now = time.monotonic()
    cached = _timing_cache.get(cache_key)
    if cached and cached.expires_at > now:
        all_timings = deepcopy(cached.value)
    else:
        lock = _timing_locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            cached = _timing_cache.get(cache_key)
            now = time.monotonic()
            if cached and cached.expires_at > now:
                all_timings = deepcopy(cached.value)
            else:
                try:
                    static_data = await get_nus_static_data(db_client)
                    route_codes = get_nus_route_codes(static_data)
                    url = f"{NUS_NEXTBUS_BASE_URL}/stop/{quote(normalized_stop_code)}"
                    html = await _get_text(url)
                    all_timings = parse_nus_timing_html(html, route_codes)
                    _timing_cache[cache_key] = CacheEntry(
                        time.monotonic() + NUS_TIMING_CACHE_SECONDS,
                        deepcopy(all_timings),
                    )
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 404:
                        raise HTTPException(404, "NUS bus stop not found") from exc
                    emit_exception_log(
                        "warning",
                        "nus_nextbus_http_status_error",
                        exc,
                        stop_code=normalized_stop_code,
                        status_code=exc.response.status_code,
                    )
                    raise HTTPException(503, "Error contacting NUS NextBus") from exc
                except httpx.RequestError as exc:
                    emit_exception_log(
                        "warning",
                        "nus_nextbus_request_error",
                        exc,
                        stop_code=normalized_stop_code,
                    )
                    raise HTTPException(503, "Error contacting NUS NextBus") from exc

    if process_all:
        return all_timings

    return [
        timing
        for timing in all_timings
        if timing.get("serviceNo") in requested_services
    ]


def current_sgt_timestamp() -> str:
    sgt_timezone = pytz.timezone("Asia/Singapore")
    return datetime.now(sgt_timezone).isoformat()
