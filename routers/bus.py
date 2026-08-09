from datetime import datetime
import json
import time
from typing import List, Optional
import uuid
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
import httpx
from pydantic import BaseModel
import pytz
from routers.database import getDBClient
from routers.nus_nextbus import (
    BUS_STOP_AVAILABLE_SERVICES_KEY,
    NUS_BUS_STATIC_KEY,
    build_nus_stop_services_lookup,
    current_sgt_timestamp,
    fetch_nus_static_data,
    format_nus_bus_route_raw,
    format_nus_bus_routes,
    format_nus_bus_stops,
    is_lta_stop_code,
    merge_bus_stop_available_services,
)
from routers.utils import (
    cache_headers,
    emit_route_exception,
    emit_route_http_error,
    getBusRoutesFromLTA,
    getBusServicesFromLTA,
    getFormattedBusRoutesData,
    map_bus_services,
    restructure_to_stops_only,
)
from routers.cache import ROUTE_CACHE_TTLS, blob_cache

dbClient = getDBClient()

bus_router = APIRouter()

class DeleteRequest(BaseModel):
    serviceNumbers: list[str]

    
GEOJSON_URL = "https://data.busrouter.sg/v1/routes.min.geojson"

class PolylineRequest(BaseModel):
    serviceNumbers: list[str]


def _parse_json_value(value):
    if isinstance(value, str):
        return json.loads(value)
    return value


def _preserve_non_lta_stop_services(existing, refreshed_lta: dict) -> dict:
    if not existing:
        return refreshed_lta

    existing_data = _parse_json_value(existing)
    if not isinstance(existing_data, dict):
        return refreshed_lta

    merged = dict(refreshed_lta)
    for stop_code, services in existing_data.items():
        if not is_lta_stop_code(str(stop_code)):
            merged[str(stop_code)] = services
    return merged

@bus_router.api_route("/health", methods=["GET", "HEAD"])
async def health_check(request: Request):
    """
    Health check endpoint to ensure the API is running.
    This route will respond to both GET and HEAD requests.
    """
    if request.method == "HEAD":
        return {}
    return {"status": "API is running"}

@bus_router.get("/extractBusRoutesRawData")
async def extract_bus_routes_raw_data(request: Request):
    t0 = time.perf_counter()
    stage = "fetch_lta_bus_routes"
    try:
        bus_route_key = "busRouteRaw"
        raw_data = await getBusRoutesFromLTA()
        stage = "restructure_stops_only"
        stops_data = restructure_to_stops_only(raw_data)

        sgt_timezone = pytz.timezone("Asia/Singapore")
        current_timestamp = datetime.now(sgt_timezone).isoformat()

        formatted_data = [
            {
                "id": str(bus_stop_code),
                "bus_stop_code": str(bus_stop_code),
                "json_value": json.dumps(bus_stop_data),  # Convert dict to JSON string
                "modified_at": current_timestamp
            }
            for bus_stop_code, bus_stop_data in stops_data.items()
        ]

        # Upsert data into the bus_route_raw table
        stage = "upsert_bus_route_raw"
        response = dbClient.table("bus_route_raw").upsert(
            formatted_data,
            on_conflict="id"  # Update if id already exists
        ).execute()

        # # Check if the operation was successful
        if not response.data:
            raise HTTPException(status_code=500, detail="Failed to store bus routes data in Supabase")

        return {"message": "Extracted and stored successfully"}

    except HTTPException as exc:
        emit_route_http_error("/extractBusRoutesRawData", request, exc, t0, stage=stage)
        raise
    except Exception as exc:
        print(f"Error processing bus routes data: {exc}")
        emit_route_exception("/extractBusRoutesRawData", request, exc, t0, stage=stage)
        raise HTTPException(status_code=500, detail=f"Error: {str(exc)}")

@bus_router.get("/bus-routes/stops")
async def get_bus_routes_by_stops(request: Request):
    """
    Get bus routes data organized by bus stops only.
    """
    t0 = time.perf_counter()
    stage = "load_bus_route_raw"
    try:
        async def build_payload():
            response = dbClient.table("bus_route_raw").select("bus_stop_code, json_value").execute()

            if not response.data:
                return {"message": "No records available"}

            return {
                row["bus_stop_code"]: json.loads(row["json_value"])
                for row in response.data
            }

        return await blob_cache.get_cached_or_generate(
            request=request,
            route_key="/bus-routes/stops",
            ttl_seconds=ROUTE_CACHE_TTLS["/bus-routes/stops"],
            generator=build_payload,
        )

    except HTTPException as exc:
        emit_route_http_error("/bus-routes/stops", request, exc, t0, stage=stage)
        raise
    except Exception as exc:
        print(f"Error fetching bus route data: {exc}")
        emit_route_exception("/bus-routes/stops", request, exc, t0, stage=stage)
        raise HTTPException(status_code=500, detail="Error fetching bus route data")

@bus_router.get("/extractBusRoutesData")
async def extract_bus_stops(request: Request):
    """
    Extract bus routes data and upsert into Supabase if not already extracted.
    - Checks if bus_routes and jsons tables have data.
    - Upserts formatted_bus_route_data into bus_routes table.
    - Upserts formatted_bus_stop_available_services into jsons table.
    - Includes modified_at timestamp in SGT (GMT+8).
    - Avoids overwriting existing data.
    """
    bus_route_key = "busRoute"
    bus_stop_available_services_key = "busStopAvailableServices"

    t0 = time.perf_counter()
    stage = "fetch_lta_bus_routes"

    try:
        # Check if data exists in bus_routes table
        # bus_routes_check = dbClient.table("bus_route").select("service_no", count="exact").limit(1).execute()
        # bus_routes_exists = bus_routes_check.count > 0

        # # Check if data exists in jsons table for bus_stop_available_services_key
        # jsons_check = dbClient.table("jsons").select("id").eq("id", bus_stop_available_services_key).execute()
        # jsons_exists = len(jsons_check.data) > 0

        # # If both datasets exist, return message
        # if bus_routes_exists and jsons_exists:
        #     return {"message": "Already Extracted"}

        # If either dataset is missing, extract and upsert
        raw_bus_route_data = await getBusRoutesFromLTA()
        stage = "format_routes"
        formatted_bus_route_data, formatted_bus_stop_available_services = getFormattedBusRoutesData(raw_bus_route_data)

        stage = "merge_existing_non_lta_stop_services"
        existing_services_response = (
            dbClient.table("jsons")
            .select("json_value")
            .eq("id", bus_stop_available_services_key)
            .execute()
        )
        existing_services = (
            existing_services_response.data[0]["json_value"]
            if existing_services_response.data
            else {}
        )
        formatted_bus_stop_available_services = _preserve_non_lta_stop_services(
            existing_services,
            formatted_bus_stop_available_services,
        )

        # Get current timestamp in Singapore time (GMT+8)
        sgt_timezone = pytz.timezone("Asia/Singapore")
        current_timestamp = datetime.now(sgt_timezone).isoformat()

        # Prepare bus routes data for upsert
        formatted_bus_routes = [
            {
                "id": uuid.uuid4().hex[:12],
                "service_no": str(bus_route["serviceNo"]),  # Ensure string format
                "json_value": json.dumps(bus_route),  # Store full JSON object
                "modified_at": current_timestamp
            }
            for bus_route in formatted_bus_route_data
        ]

        # Debug: Print number of bus routes
        print(f"Prepared {len(formatted_bus_routes)} bus route records for upsert")

        # Upsert bus routes in batches
        batch_size = 1000
        for i in range(0, len(formatted_bus_routes), batch_size):
            batch = formatted_bus_routes[i:i + batch_size]
            # response = dbClient.table("bus_route").upsert(
            #     batch,
            #     on_conflict="service_no"
            # ).execute()

            # Debug: Print batch progress
            print(f"Upserted bus routes batch {i // batch_size + 1}: {len(batch)} records")

            # Check if the operation was successful
            # if not response.data:
            #     raise HTTPException(status_code=500, detail="Failed to upsert bus routes data")

        # Prepare bus stop available services data for upsert
        formatted_bus_stop_services = {
            "id": bus_stop_available_services_key,
            "json_value": json.dumps(formatted_bus_stop_available_services),
            "modified_at": current_timestamp
        }

        # Debug: Print bus stop services data
        print(f"Prepared bus stop available services: {bus_stop_available_services_key}")

        # Upsert bus stop available services
        stage = "upsert_jsons"
        response = dbClient.table("jsons").upsert(
            [formatted_bus_stop_services],
            on_conflict="id"
        ).execute()

        # Check if the operation was successful
        if not response.data:
            raise HTTPException(status_code=500, detail="Failed to upsert bus stop available services data")

        return {"message": formatted_bus_route_data}

    except HTTPException as exc:
        emit_route_http_error("/extractBusRoutesData", request, exc, t0, stage=stage)
        raise
    except Exception as exc:
        print(f"Error processing bus routes data: {exc}")
        emit_route_exception("/extractBusRoutesData", request, exc, t0, stage=stage)
        raise HTTPException(status_code=500, detail=f"Error: {str(exc)}")


@bus_router.post("/extractNusBusData")
async def extract_nus_bus_data(request: Request):
    t0 = time.perf_counter()
    stage = "fetch_nus_static_data"

    try:
        static_data = await fetch_nus_static_data()
        current_timestamp = current_sgt_timestamp()

        stage = "format_nus_data"
        bus_stop_rows = format_nus_bus_stops(static_data, current_timestamp)
        bus_route_rows = format_nus_bus_routes(static_data, current_timestamp)
        bus_route_raw_rows = format_nus_bus_route_raw(static_data, current_timestamp)
        nus_stop_services = build_nus_stop_services_lookup(static_data)

        if bus_stop_rows:
            stage = "upsert_nus_bus_stops"
            response = (
                dbClient.table("bus_stops")
                .upsert(bus_stop_rows, on_conflict="id")
                .execute()
            )
            if not response.data:
                raise HTTPException(status_code=500, detail="Failed to upsert NUS bus stops")

        if bus_route_rows:
            stage = "upsert_nus_bus_routes"
            response = (
                dbClient.table("bus_route")
                .upsert(bus_route_rows, on_conflict="service_no")
                .execute()
            )
            if not response.data:
                raise HTTPException(status_code=500, detail="Failed to upsert NUS bus routes")

        if bus_route_raw_rows:
            stage = "upsert_nus_bus_route_raw"
            response = (
                dbClient.table("bus_route_raw")
                .upsert(bus_route_raw_rows, on_conflict="id")
                .execute()
            )
            if not response.data:
                raise HTTPException(status_code=500, detail="Failed to upsert NUS raw bus routes")

        stage = "load_existing_stop_services"
        existing_services_response = (
            dbClient.table("jsons")
            .select("json_value")
            .eq("id", BUS_STOP_AVAILABLE_SERVICES_KEY)
            .execute()
        )
        existing_services = (
            existing_services_response.data[0]["json_value"]
            if existing_services_response.data
            else {}
        )
        merged_stop_services = merge_bus_stop_available_services(
            existing_services,
            nus_stop_services,
        )

        stage = "upsert_nus_jsons"
        response = (
            dbClient.table("jsons")
            .upsert(
                [
                    {
                        "id": BUS_STOP_AVAILABLE_SERVICES_KEY,
                        "json_value": json.dumps(merged_stop_services, separators=(",", ":")),
                        "modified_at": current_timestamp,
                    },
                    {
                        "id": NUS_BUS_STATIC_KEY,
                        "json_value": json.dumps(static_data, separators=(",", ":")),
                        "modified_at": current_timestamp,
                    },
                ],
                on_conflict="id",
            )
            .execute()
        )
        if not response.data:
            raise HTTPException(status_code=500, detail="Failed to upsert NUS JSON metadata")

        stage = "purge_cache"
        for key in ("/getallbusstops", "/getBusRoutesData", "/bus-routes/stops"):
            blob_cache.delete(key)

        return {
            "message": "NUS bus data processed successfully",
            "stops": len(bus_stop_rows),
            "routes": len(bus_route_rows),
            "rawRouteStops": len(bus_route_raw_rows),
            "updatedBusStopAvailableServices": True,
        }

    except HTTPException as exc:
        emit_route_http_error("/extractNusBusData", request, exc, t0, stage=stage)
        raise
    except httpx.HTTPError as exc:
        emit_route_exception("/extractNusBusData", request, exc, t0, stage=stage)
        raise HTTPException(status_code=503, detail="Failed to fetch NUS bus data") from exc
    except Exception as exc:
        print(f"Error processing NUS bus data: {exc}")
        emit_route_exception("/extractNusBusData", request, exc, t0, stage=stage)
        raise HTTPException(status_code=500, detail=f"Error: {str(exc)}")
    
@bus_router.get("/getBusRoutesData")
async def get_bus_route_data(request: Request):
    t0 = time.perf_counter()
    stage = "load_bus_routes"
    try:
        async def build_payload():
            response = dbClient.table("bus_route").select("service_no, json_value").execute()

            if not response.data:
                return {"message": "No records available"}

            combined_data = []
            for row in response.data:
                json_value = row["json_value"]
                data = json.loads(json_value) if isinstance(json_value, str) else json_value
                combined_data.append(data)

            return combined_data

        return await blob_cache.get_cached_or_generate(
            request=request,
            route_key="/getBusRoutesData",
            ttl_seconds=ROUTE_CACHE_TTLS["/getBusRoutesData"],
            generator=build_payload,
        )
    except HTTPException as exc:
        emit_route_http_error("/getBusRoutesData", request, exc, t0, stage=stage)
        raise
    except Exception as exc:
        print(f"Error fetching bus route data: {exc}")
        emit_route_exception("/getBusRoutesData", request, exc, t0, stage=stage)
        raise HTTPException(status_code=500, detail="Error fetching bus route data")
    
@bus_router.get("/getBusStopAvailableBussesData")
async def get_bus_stop_available_busses_data(request: Request):
    key = "busStopAvailableServices"
    t0 = time.perf_counter()
    stage = "load_bus_stop_services"
    try:
        response = dbClient.table("jsons").select("json_value").eq("id", key).execute()
        if response.data:
            return response.data[0]["json_value"]
        else:
            return {"message": "No records available"}
    except HTTPException as exc:
        emit_route_http_error("/getBusStopAvailableBussesData", request, exc, t0, stage=stage)
        raise
    except Exception as exc:
        print(f"Error fetching bus stop available busses data: {exc}")
        emit_route_exception("/getBusStopAvailableBussesData", request, exc, t0, stage=stage)
        raise HTTPException(status_code=500, detail="Error fetching bus stop available busses data")
    
@bus_router.get("/getBusServicesData")
async def get_bus_services_data(request: Request, overwrite: Optional[bool] = False):
    print(overwrite)
    pbKey = "busServices"
    t0 = time.perf_counter()
    stage = "load_bus_services"

    sgt_timezone = pytz.timezone("Asia/Singapore")
    current_timestamp = datetime.now(sgt_timezone).isoformat()
    try:
        if not overwrite:
            # Get data from the database
            db_data = dbClient.table("jsons").select("json_value").eq("id", pbKey).execute()
            if db_data.data[0]["json_value"]:
                data = db_data.data[0]["json_value"]
                if isinstance(data, str):
                    data = json.loads(data)
                return JSONResponse(content=data, headers=cache_headers())
                # return db_data.__dict__["json_value"]
            else:
                # If no data in DB, fetch from API, map, and save.
                stage = "fetch_lta_bus_services"
                busServices = await getBusServicesFromLTA()
                if not busServices:
                    return []
                stage = "map_bus_services"
                camelcased_bus_services = map_bus_services(busServices)
                formatted_bus_stop_services = {
                    "id": pbKey,
                    "json_value": json.dumps(camelcased_bus_services),
                    "modified_at": current_timestamp
                }

                # Upsert bus stop available services
                stage = "upsert_jsons"
                response = dbClient.table("jsons").upsert(
                    [formatted_bus_stop_services],
                    on_conflict="id"
                ).execute()
                return camelcased_bus_services

        else:
            # Overwrite or fetch, map, and save to DB
            stage = "fetch_lta_bus_services"
            busServices = await getBusServicesFromLTA()
            if not busServices:
                return []
            stage = "map_bus_services"
            camelcased_bus_services = map_bus_services(busServices)
            formatted_bus_stop_services = {
                "id": pbKey,
                "json_value": json.dumps(camelcased_bus_services),
                "modified_at": current_timestamp
            }

            # Upsert bus stop available services
            stage = "upsert_jsons"
            response = dbClient.table("jsons").upsert(
                [formatted_bus_stop_services],
                on_conflict="id"
            ).execute()
            return camelcased_bus_services

    except HTTPException as http_exc:
        emit_route_http_error(
            "/getBusServicesData",
            request,
            http_exc,
            t0,
            stage=stage,
            overwrite=overwrite,
        )
        raise http_exc
    except Exception as exc:
        print(f"Error retrieving bus services: {exc}")
        emit_route_exception(
            "/getBusServicesData",
            request,
            exc,
            t0,
            stage=stage,
            overwrite=overwrite,
        )
        raise HTTPException(status_code=500, detail=f"Error retrieving bus services: {exc}")
    

class BusRoute(BaseModel):
    serviceNo: str
    routes: List[dict]

class BusRouteBulkUpdate(BaseModel):
    bus_routes: List[BusRoute]

@bus_router.post("/bulkUpdateBusRoutes")
async def bulk_update_bus_routes(request: Request, data: BusRouteBulkUpdate):
    """
    Bulk update bus routes data in Supabase.
    - Accepts a list of bus route objects with updated polyline values.
    - Upserts into bus_route table based on service_no.
    - Updates json_value and modified_at (SGT) for existing rows.
    - Inserts new rows with new UUIDs for id.
    """
    t0 = time.perf_counter()
    stage = "format_routes"

    try:
        sgt_timezone = pytz.timezone("Asia/Singapore")
        current_timestamp = datetime.now(sgt_timezone).isoformat()

        formatted_bus_routes = [
            {
                "id": uuid.uuid4().hex[:12],  
                "service_no": str(bus_route.serviceNo), 
                "json_value": json.dumps(bus_route.dict()),
                "modified_at": current_timestamp
            }
            for bus_route in data.bus_routes
        ]

        print(f"Prepared {len(formatted_bus_routes)} bus route records for upsert")

        batch_size = 1000
        for i in range(0, len(formatted_bus_routes), batch_size):
            stage = "upsert_bus_route_batch"
            batch = formatted_bus_routes[i:i + batch_size]
            response = dbClient.table("bus_route").upsert(
                batch,
                on_conflict="service_no"
            ).execute()

            print(f"Upserted bus routes batch {i // batch_size + 1}: {len(batch)} records")

            if not response.data:
                raise HTTPException(status_code=500, detail="Failed to upsert bus routes data")

        stored_routes = dbClient.table("bus_route").select("service_no", count="exact").execute()
        print(f"Total stored bus routes: {stored_routes.count}")

        return {"message": "Bulk update successful"}

    except HTTPException as exc:
        emit_route_http_error(
            "/bulkUpdateBusRoutes",
            request,
            exc,
            t0,
            stage=stage,
            service_numbers=[route.serviceNo for route in data.bus_routes],
            service_numbers_count=len(data.bus_routes),
        )
        raise
    except Exception as exc:
        print(f"Error processing bulk update: {exc}")
        emit_route_exception(
            "/bulkUpdateBusRoutes",
            request,
            exc,
            t0,
            stage=stage,
            service_numbers=[route.serviceNo for route in data.bus_routes],
            service_numbers_count=len(data.bus_routes),
        )
        raise HTTPException(status_code=500, detail=f"Error: {str(exc)}")

@bus_router.post("/bus-routes/polylines")
async def get_bus_routes_with_polylines(request: Request, body: PolylineRequest):
    t0 = time.perf_counter()
    stage = "fetch_geojson"
    try:
        # 1. Fetch GeoJSON and build O(1) lookup: {"serviceNo|direction": [[lat, lng], ...]}
        async with httpx.AsyncClient() as client:
            geojson_res = await client.get(GEOJSON_URL)
            if geojson_res.status_code != 200:
                raise HTTPException(status_code=502, detail="Failed to fetch GeoJSON source")
            geojson = geojson_res.json()

        lookup: dict[str, list[list[float]]] = {}
        for feature in geojson.get("features", []):
            props = feature.get("properties", {})
            service_no = str(props.get("number", ""))
            pattern = props.get("pattern")
            direction = {0: "1", 1: "2"}.get(pattern)
            if direction is None:
                continue
            coords = feature.get("geometry", {}).get("coordinates", [])
            if not coords:
                continue
            transformed = [[lat, lng] for lng, lat in coords]
            key = f"{service_no}|{direction}"
            if key in lookup:
                lookup[key].extend(transformed)
            else:
                lookup[key] = transformed

        stage = "fetch_lta_bus_routes"
        raw_bus_route_data = await getBusRoutesFromLTA()
        stage = "format_routes"
        formatted_bus_route_data, _ = getFormattedBusRoutesData(raw_bus_route_data)

        requested = set(body.serviceNumbers)
        result = []
        for svc in formatted_bus_route_data:
            if svc["serviceNo"] not in requested:
                continue
            routes = []
            for route in svc["routes"]:
                key = f"{svc['serviceNo']}|{route['direction']}"
                coords = lookup.get(key)
                polyline = json.dumps(coords, separators=(",", ":")) if coords else ""
                routes.append({**route, "polyline": polyline})
            result.append({**svc, "routes": routes})

        return {"bus_routes" : result}
    except HTTPException as exc:
        emit_route_http_error(
            "/bus-routes/polylines",
            request,
            exc,
            t0,
            stage=stage,
            service_numbers=body.serviceNumbers,
            service_numbers_count=len(body.serviceNumbers),
        )
        raise
    except Exception as exc:
        emit_route_exception(
            "/bus-routes/polylines",
            request,
            exc,
            t0,
            stage=stage,
            service_numbers=body.serviceNumbers,
            service_numbers_count=len(body.serviceNumbers),
        )
        raise

@bus_router.delete("/bus-routes")
async def delete_bus_routes(request: Request, body: DeleteRequest):
    t0 = time.perf_counter()
    stage = "validate_payload"

    try:
        if not body.serviceNumbers:
            raise HTTPException(status_code=400, detail="`serviceNumbers` must be a non-empty list.")

        stage = "delete_bus_routes"
        response = (
            dbClient.table("bus_route")
            .delete()
            .in_("service_no", body.serviceNumbers)
            .execute()
        )

        deleted = response.data or []

        return {
            "deleted": len(deleted),
            "serviceNumbers": [row["service_no"] for row in deleted],
        }
    except HTTPException as exc:
        emit_route_http_error(
            "bus-routes",
            request,
            exc,
            t0,
            stage=stage,
            service_numbers=body.serviceNumbers,
            service_numbers_count=len(body.serviceNumbers),
        )
        raise
    except Exception as exc:
        emit_route_exception(
            "bus-routes",
            request,
            exc,
            t0,
            stage=stage,
            service_numbers=body.serviceNumbers,
            service_numbers_count=len(body.serviceNumbers),
        )
        raise

@bus_router.post("/cache/purge")
async def purge_cache(key: str = None):
    if key:
        deleted = blob_cache.delete(key)
        return {"message": f"Cache key '{key}' purged", "deleted": deleted}
    deleted = blob_cache.clear()
    return {"message": "All cache purged", "deleted": deleted}
