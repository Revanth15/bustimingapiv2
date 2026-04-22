import json
import re
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, List, Optional

import httpx
import pytz
from fastapi import APIRouter, HTTPException, Query, Request

from routers.cache import ROUTE_CACHE_TTLS, blob_cache
from routers.database import getDBClient
from routers.utils import queryAPI

dbClient = getDBClient()
MRT_router = APIRouter()

RAIL_GEOJSON_URL = "https://raw.githubusercontent.com/cheeaun/sgraildata/master/data/v1/sg-rail.geojson"
RAIL_LINES_ROW_ID = "railLinesV1"
RAIL_STATIONS_ROW_ID = "railStationsV1"
RAIL_STATION_EXITS_ROW_ID = "railStationExitsV1"

RAIL_LINES_ROUTE_KEY = "/getRailLinesData"
RAIL_STATIONS_ROUTE_KEY = "/getRailStationsData"
RAIL_STATION_EXITS_ROUTE_KEY = "/getRailStationExitsData"

COLOR_MAP = {
    "orangered": "#FF4500",
    "mediumseagreen": "#3CB371",
    "darkslateblue": "#483D8B",
    "darkmagenta": "#8B008B",
    "saddlebrown": "#8B4513",
    "orange": "#FFA500",
    "gray": "#808080",
    "red": "#FF0000",
    "green": "#008000",
    "yellow": "#FFFF00",
    "blue": "#0000FF",
    "purple": "#800080",
    "brown": "#A52A2A",
}


def _current_sgt_timestamp() -> str:
    sgt_timezone = pytz.timezone("Asia/Singapore")
    return datetime.now(sgt_timezone).isoformat()


async def _fetch_rail_geojson() -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(RAIL_GEOJSON_URL)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Failed to fetch rail GeoJSON source") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise ValueError("Upstream rail GeoJSON returned invalid JSON") from exc

    if payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
        raise ValueError("Upstream rail GeoJSON is missing a valid features array")

    return payload


def _split_station_codes(raw: str) -> list[str]:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("station_codes is required")
    return [part.strip() for part in raw.split("-") if part.strip()]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower())
    return re.sub(r"-+", "-", slug).strip("-")


def _normalize_network(raw: str) -> list[str]:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("network is required")

    raw_lower = raw.lower()
    networks: list[str] = []
    if "mrt" in raw_lower:
        networks.append("mrt")
    if "lrt" in raw_lower:
        networks.append("lrt")

    if not networks:
        raise ValueError(f"Unknown rail network token: {raw}")

    return networks


def _normalize_color(raw: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("rail color token is required")

    token = raw.strip().lower()
    if token not in COLOR_MAP:
        raise ValueError(f"Unknown rail color token: {raw}")
    return COLOR_MAP[token]


def _to_lat_lng_pair(lng_lat: list[float]) -> list[float]:
    if not isinstance(lng_lat, list) or len(lng_lat) < 2:
        raise ValueError("Coordinate pair must contain longitude and latitude")
    lng, lat = lng_lat[:2]
    return [round(float(lat), 6), round(float(lng), 6)]


def _normalize_line_geometry(geometry: dict[str, Any]) -> list[list[list[float]]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")

    if geometry_type == "LineString":
        return [[_to_lat_lng_pair(point) for point in coordinates]]
    if geometry_type == "MultiLineString":
        return [[_to_lat_lng_pair(point) for point in path] for path in coordinates]

    raise ValueError(f"Unsupported line geometry type: {geometry_type}")


def _normalize_polygon_geometry(geometry: dict[str, Any]) -> list[list[list[list[float]]]]:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")

    if geometry_type == "Polygon":
        return [[[_to_lat_lng_pair(point) for point in ring] for ring in coordinates]]
    if geometry_type == "MultiPolygon":
        return [
            [[_to_lat_lng_pair(point) for point in ring] for ring in polygon]
            for polygon in coordinates
        ]

    raise ValueError(f"Unsupported polygon geometry type: {geometry_type}")


def _build_station_index(features: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    station_index: dict[str, dict[str, Any]] = {}

    for feature in features:
        geometry_type = feature.get("geometry", {}).get("type")
        properties = feature.get("properties", {})

        if geometry_type != "Point" or properties.get("stop_type") != "station":
            continue

        station_codes_raw = properties.get("station_codes")
        station_codes = _split_station_codes(station_codes_raw)
        station_colors_raw = properties.get("station_colors", "")
        line_colors_hex = [_normalize_color(token) for token in station_colors_raw.split("-") if token]

        station_index[station_codes_raw] = {
            "id": station_codes_raw.lower(),
            "name": properties.get("name", ""),
            "station_codes": station_codes,
            "primary_station_code": station_codes[0],
            "networks": _normalize_network(properties.get("network", "")),
            "line_colors_hex": line_colors_hex,
        }

    if not station_index:
        raise ValueError("No station metadata features found in upstream rail GeoJSON")

    return station_index


def _build_lines_payload(features: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    lines = []

    for feature in features:
        geometry = feature.get("geometry", {})
        geometry_type = geometry.get("type")
        if geometry_type not in {"LineString", "MultiLineString"}:
            continue

        properties = feature.get("properties", {})
        line_name = properties.get("name")
        raw_networks = _normalize_network(properties.get("network", ""))
        if len(raw_networks) != 1:
            raise ValueError(f"Line feature has unexpected network value: {properties.get('network')}")

        lines.append(
            {
                "id": _slugify(line_name),
                "name": line_name,
                "network": raw_networks[0],
                "color_hex": _normalize_color(properties.get("line_color", "")),
                "paths": _normalize_line_geometry(geometry),
            }
        )

    if not lines:
        raise ValueError("No line features found in upstream rail GeoJSON")

    return {"lines": sorted(lines, key=lambda item: item["name"])}


def _build_stations_payload(
    features: list[dict[str, Any]],
    station_index: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    grouped_polygons: dict[str, list[list[list[list[float]]]]] = defaultdict(list)

    for feature in features:
        geometry = feature.get("geometry", {})
        geometry_type = geometry.get("type")
        if geometry_type not in {"Polygon", "MultiPolygon"}:
            continue

        station_codes_raw = feature.get("properties", {}).get("station_codes")
        if station_codes_raw not in station_index:
            raise ValueError(f"Missing station metadata for polygon station_codes={station_codes_raw}")

        grouped_polygons[station_codes_raw].extend(_normalize_polygon_geometry(geometry))

    stations = []
    for station_codes_raw, station in station_index.items():
        polygons = grouped_polygons.get(station_codes_raw)
        if not polygons:
            raise ValueError(f"Missing station polygons for station_codes={station_codes_raw}")

        stations.append({**station, "polygons": polygons})

    return {"stations": sorted(stations, key=lambda item: (item["primary_station_code"], item["name"]))}


def _build_exits_payload(
    features: list[dict[str, Any]],
    station_index: dict[str, dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    deduped_exits: dict[tuple[str, str, float, float], dict[str, Any]] = {}

    for feature in features:
        geometry = feature.get("geometry", {})
        properties = feature.get("properties", {})
        if geometry.get("type") != "Point" or properties.get("stop_type") != "entrance":
            continue

        station_codes_raw = properties.get("station_codes")
        station = station_index.get(station_codes_raw)
        if station is None:
            raise ValueError(f"Missing station metadata for exit station_codes={station_codes_raw}")

        exit_code = str(properties.get("exit_code") or properties.get("name") or "").strip()
        if not exit_code:
            raise ValueError(f"Missing exit code for station_codes={station_codes_raw}")

        latitude, longitude = _to_lat_lng_pair(geometry.get("coordinates", []))
        dedupe_key = (station_codes_raw, exit_code.upper(), latitude, longitude)
        deduped_exits[dedupe_key] = {
            "id": f"{station['id']}-exit-{_slugify(exit_code)}",
            "station_id": station["id"],
            "station_name": station["name"],
            "station_codes": station["station_codes"],
            "exit_code": exit_code.upper(),
            "latitude": latitude,
            "longitude": longitude,
        }

    exits = sorted(
        deduped_exits.values(),
        key=lambda item: (item["station_id"], item["exit_code"], item["latitude"], item["longitude"]),
    )
    return {"exits": exits}


def _upsert_rail_payloads(
    lines_payload: dict[str, Any],
    stations_payload: dict[str, Any],
    exits_payload: dict[str, Any],
) -> None:
    current_timestamp = _current_sgt_timestamp()
    rows = [
        {"id": RAIL_LINES_ROW_ID, "json_value": lines_payload, "modified_at": current_timestamp},
        {"id": RAIL_STATIONS_ROW_ID, "json_value": stations_payload, "modified_at": current_timestamp},
        {"id": RAIL_STATION_EXITS_ROW_ID, "json_value": exits_payload, "modified_at": current_timestamp},
    ]

    response = dbClient.table("jsons").upsert(rows, on_conflict="id").execute()
    if getattr(response, "data", None) is None:
        raise HTTPException(status_code=500, detail="Failed to store rail map data in Supabase")


async def _build_and_seed_all_rail_payloads() -> dict[str, dict[str, Any]]:
    geojson = await _fetch_rail_geojson()
    features = geojson.get("features", [])

    station_index = _build_station_index(features)
    lines_payload = _build_lines_payload(features)
    stations_payload = _build_stations_payload(features, station_index)
    exits_payload = _build_exits_payload(features, station_index)

    _upsert_rail_payloads(lines_payload, stations_payload, exits_payload)

    return {
        RAIL_LINES_ROW_ID: lines_payload,
        RAIL_STATIONS_ROW_ID: stations_payload,
        RAIL_STATION_EXITS_ROW_ID: exits_payload,
    }


async def _load_json_row_or_seed(
    row_id: str,
    builder_fn: Callable[[], Any],
) -> dict[str, Any]:
    try:
        response = dbClient.table("jsons").select("json_value").eq("id", row_id).execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Error fetching rail map data") from exc

    if response.data:
        json_value = response.data[0]["json_value"]
        return json.loads(json_value) if isinstance(json_value, str) else json_value

    try:
        seeded_payloads = builder_fn()
        if hasattr(seeded_payloads, "__await__"):
            seeded_payloads = await seeded_payloads
    except HTTPException as exc:
        if exc.status_code in {500, 502}:
            raise HTTPException(status_code=503, detail="Rail map data is unavailable") from exc
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Rail map data is unavailable") from exc

    payload = seeded_payloads.get(row_id)
    if payload is None:
        raise HTTPException(status_code=503, detail="Rail map data is unavailable")
    return payload


@MRT_router.get("/mrt_crowd_density")
async def get_mrt_crowd_density(mrt_lines: List[str] = Query(..., description="List of MRT lines")):
    try:
        start_time = time.perf_counter()
        all_results = {}

        for mrt_line in mrt_lines:
            ltaResponse = await queryAPI("ltaodataservice/PCDRealTime", {"TrainLine": mrt_line})
            mrtCrowdDensityRes = ltaResponse.get("value", [])

            if not mrtCrowdDensityRes:
                all_results[mrt_line] = {
                    "StartTime": "",
                    "EndTime": "",
                    "Stations": []
                }
                continue

            first_entry = mrtCrowdDensityRes[0]
            res = {
                "StartTime": first_entry.get("StartTime", ""),
                "EndTime": first_entry.get("EndTime", ""),
                "Stations": []
            }

            res["Stations"] = [
                {
                    "Station": station.get("Station", ""),
                    "CrowdLevel": station.get("CrowdLevel", "")
                }
                for station in mrtCrowdDensityRes
            ]

            all_results[mrt_line] = res

        end_time = time.perf_counter()
        loop_duration = end_time - start_time
        print(f"Processing took {loop_duration:.6f} seconds")

        return {
            "lines": all_results,
            "processing_time_seconds": loop_duration
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@MRT_router.get("/extractRailMapData")
async def extract_rail_map_data():
    try:
        payloads = await _build_and_seed_all_rail_payloads()
    except HTTPException as exc:
        raise exc
    except Exception as exc:
        print(f"Error processing rail map data: {exc}")
        raise HTTPException(status_code=500, detail=f"Error processing rail map data: {exc}") from exc

    blob_cache.delete(RAIL_LINES_ROUTE_KEY)
    blob_cache.delete(RAIL_STATIONS_ROUTE_KEY)
    blob_cache.delete(RAIL_STATION_EXITS_ROUTE_KEY)

    return {
        "message": "Rail map data refreshed",
        "counts": {
            "lines": len(payloads[RAIL_LINES_ROW_ID]["lines"]),
            "stations": len(payloads[RAIL_STATIONS_ROW_ID]["stations"]),
            "exits": len(payloads[RAIL_STATION_EXITS_ROW_ID]["exits"]),
        },
        "supabase_ids": [RAIL_LINES_ROW_ID, RAIL_STATIONS_ROW_ID, RAIL_STATION_EXITS_ROW_ID],
    }


@MRT_router.get("/getRailLinesData")
async def get_rail_lines_data(request: Request):
    try:
        return await blob_cache.get_cached_or_generate(
            request=request,
            route_key=RAIL_LINES_ROUTE_KEY,
            ttl_seconds=ROUTE_CACHE_TTLS[RAIL_LINES_ROUTE_KEY],
            generator=lambda: _load_json_row_or_seed(RAIL_LINES_ROW_ID, _build_and_seed_all_rail_payloads),
        )
    except HTTPException as exc:
        raise exc
    except Exception as exc:
        print(f"Error fetching rail lines data: {exc}")
        raise HTTPException(status_code=500, detail="Error fetching rail lines data") from exc


@MRT_router.get("/getRailStationsData")
async def get_rail_stations_data(request: Request):
    try:
        return await blob_cache.get_cached_or_generate(
            request=request,
            route_key=RAIL_STATIONS_ROUTE_KEY,
            ttl_seconds=ROUTE_CACHE_TTLS[RAIL_STATIONS_ROUTE_KEY],
            generator=lambda: _load_json_row_or_seed(RAIL_STATIONS_ROW_ID, _build_and_seed_all_rail_payloads),
        )
    except HTTPException as exc:
        raise exc
    except Exception as exc:
        print(f"Error fetching rail stations data: {exc}")
        raise HTTPException(status_code=500, detail="Error fetching rail stations data") from exc


@MRT_router.get("/getRailStationExitsData")
async def get_rail_station_exits_data(request: Request):
    try:
        return await blob_cache.get_cached_or_generate(
            request=request,
            route_key=RAIL_STATION_EXITS_ROUTE_KEY,
            ttl_seconds=ROUTE_CACHE_TTLS[RAIL_STATION_EXITS_ROUTE_KEY],
            generator=lambda: _load_json_row_or_seed(RAIL_STATION_EXITS_ROW_ID, _build_and_seed_all_rail_payloads),
        )
    except HTTPException as exc:
        raise exc
    except Exception as exc:
        print(f"Error fetching rail station exits data: {exc}")
        raise HTTPException(status_code=500, detail="Error fetching rail station exits data") from exc


@MRT_router.get("/getMRTStationCoords")
async def get_stationCoord_data():
    key = "stationCoords"
    try:
        response = dbClient.table("jsons").select("json_value").eq("id", key).execute()
        if response.data:
            return response.data[0]["json_value"]
        else:
            return {"message": "No records available"}
    except Exception as e:
        print(f"Error fetching mrt Station Coordinates data: {e}")
        raise HTTPException(status_code=500, detail="Error fetching mrt Station Coordinates data")