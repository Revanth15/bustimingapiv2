from datetime import datetime, timedelta, timezone
import json
import sys
import time
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
import pytz
from routers.busstop_cache import BusStopCache
from routers.cache import ROUTE_CACHE_TTLS, blob_cache
from routers.database import getDBClient
from routers.utils import (
    emit_exception_log,
    emit_route_exception,
    emit_route_http_error,
    emit_structured_log,
    process_bus_service,
    queryAPI,
    service_sort_key,
)
import asyncio
from typing import Any, Optional
import logging

logger = logging.getLogger()

_cache = BusStopCache(ttl=8.0, maxsize=500)
_sem = asyncio.Semaphore(30)

# Prevent duplicate handlers (important in serverless environments)
if not logger.handlers:
    logger.setLevel(logging.INFO)

    # Create stdout handler for INFO and below
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.DEBUG)

    # Filter: only allow INFO and DEBUG to stdout
    stdout_handler.addFilter(lambda record: record.levelno <= logging.INFO)

    # Create stderr handler for WARNING and above
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setLevel(logging.WARNING)

    # Define common log format
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    stdout_handler.setFormatter(formatter)
    stderr_handler.setFormatter(formatter)

    # Add handlers to the root logger
    logger.addHandler(stdout_handler)
    logger.addHandler(stderr_handler)

# Get a module-specific logger
logger = logging.getLogger(__name__)

dbClient = getDBClient()

busStops_router = APIRouter()
SINGAPORE_TZ = timezone(timedelta(hours=8))

def _log_bustiming_event(level: str, event: str, **context: Any) -> None:
    emit_structured_log(level, event, route="/bustiming", **context)

@busStops_router.get("/extractBusStops")
async def extract_bus_stops(request: Request):
    """
    Extract bus stop data from the LTA API and store/update in Supabase.
    - Fetches bus stops from LTA API in batches.
    - Uses bus_stop_master_list from jsons table for bus_services.
    - Upserts into bus_stops table with id as BusStopCode (TEXT).
    - Includes modified_at timestamp in SGT (GMT+8).
    """
    t0 = time.perf_counter()
    stage = "load_bus_stop_services"

    try:
        # Get bus_stop_master_list from jsons table
        logger.info("Fetching bus_stop_master_list from jsons table...")
        jsons_response = dbClient.table("jsons").select("json_value").eq("id", "busStopAvailableServices").execute()
        if not jsons_response.data:
            raise HTTPException(status_code=500, detail="busStopAvailableServices not found in jsons table")
        
        bus_stop_master_list = jsons_response.data[0]["json_value"]
        # Parse if json_value is TEXT
        if isinstance(bus_stop_master_list, str):
            bus_stop_master_list = json.loads(bus_stop_master_list)

        # Get all existing bus stops
        stage = "load_existing_stops"
        logger.info("Fetching existing bus stops from Supabase...")
        bus_stop_map = {}
        offset = 0
        batch_size = 1000
        while True:
            response = dbClient.table("bus_stops").select("id, description, latitude, longitude, road_name, bus_services").range(offset, offset + batch_size - 1).execute()
            if not response.data:
                break
            for stop in response.data:
                bus_stop_map[stop["id"]] = stop
            offset += batch_size
        logger.info(f"Fetched {len(bus_stop_map)} existing bus stops")

        # Fetch bus stops from LTA API
        stage = "fetch_lta_bus_stops"
        logger.info("Fetching bus stops from LTA API...")
        counter = 0
        results = []
        while True:
            result = await queryAPI("ltaodataservice/BusStops", {"$skip": str(counter)})
            results.append(result)
            counter += 500
            logger.debug(f"Fetched {len(result.get('value', []))} bus stops at offset {counter}")
            if counter >= 10000:  # Adjust based on API limits
                break

        # Flatten results
        data_list = [item for res in results if res.get("value") for item in res["value"]]
        logger.info(f"Fetched total {len(data_list)} bus stops from API")

        # Get current timestamp in Singapore time (GMT+8)
        sgt_timezone = pytz.timezone("Asia/Singapore")
        current_timestamp = datetime.now(sgt_timezone).isoformat()

        stage = "diff_records"
        new_busstops = []
        updated_busstops = []

        for stop in data_list:
            stop_id = stop["BusStopCode"]
            bus_services = ",".join(map(str, bus_stop_master_list.get(stop_id, [])))

            new_data = {
                "id": stop_id,
                "description": stop["Description"],
                "latitude": float(stop["Latitude"]),
                "longitude": float(stop["Longitude"]),
                "road_name": stop["RoadName"],
                "bus_services": bus_services,
                "modified_at": current_timestamp
            }

            if stop_id not in bus_stop_map:
                # New bus stop
                new_busstops.append(new_data)
            else:
                # Compare with existing record
                existing = bus_stop_map[stop_id]
                existing_data = {
                    "description": existing["description"],
                    "latitude": existing["latitude"],
                    "longitude": existing["longitude"],
                    "road_name": existing["road_name"],
                    "bus_services": existing["bus_services"]
                }
                new_data_no_id = {k: v for k, v in new_data.items() if k not in ["id", "modified_at"]}
                if existing_data != new_data_no_id:
                    updated_busstops.append(new_data)

        logger.info(f"{len(new_busstops)} new bus stops to insert")
        logger.info(f"{len(updated_busstops)} existing bus stops to update")

        # Upsert new and updated bus stops in batches
        all_busstops = new_busstops + updated_busstops
        if all_busstops:
            stage = "upsert_bus_stops"
            logger.info("Upserting bus stops (batched)...")
            batch_size = 1000
            for i in range(0, len(all_busstops), batch_size):
                batch = all_busstops[i:i + batch_size]
                response = dbClient.table("bus_stops").upsert(
                    batch,
                    on_conflict="id"
                ).execute()
                logger.debug(f"Upserted batch {i // batch_size + 1}: {len(batch)} records")
                if not response.data:
                    raise HTTPException(status_code=500, detail="Failed to upsert bus stops")

        # Verify stored data
        stage = "verify_count"
        stored_busstops = dbClient.table("bus_stops").select("id", count="exact").execute()
        logger.info(f"Total stored bus stops: {stored_busstops.count}")

        return {
            "message": "Bus stops processed successfully",
            "new": len(new_busstops),
            "updated": len(updated_busstops)
        }

    except HTTPException as exc:
        emit_route_http_error("/extractBusStops", request, exc, t0, stage=stage)
        raise
    except Exception as exc:
        logger.error(f"Error processing bus stops: {exc}")
        emit_route_exception("/extractBusStops", request, exc, t0, stage=stage)
        raise HTTPException(status_code=500, detail=f"Error: {str(exc)}")


@busStops_router.get("/getallbusstops")
async def get_all_bus_stops(request: Request):
    """
    Retrieve all bus stop information stored in PocketBase.
    """
    t0 = time.perf_counter()
    stage = "load_bus_stops"

    try:
        async def build_payload():
            response = dbClient.table("bus_stops").select(
                "id, description, latitude, longitude, road_name, bus_services"
            ).execute()

            if not response.data:
                return {"message": "No records available"}

            bus_stop_data = []
            for stop in response.data:
                bus_stop_data.append({
                    "id": stop["id"],
                    "description": stop["description"],
                    "latitude": stop["latitude"],
                    "longitude": stop["longitude"],
                    "road_name": stop["road_name"],
                    "bus_services": stop["bus_services"],
                })

            return {"busStops": bus_stop_data}

        return await blob_cache.get_cached_or_generate(
            request=request,
            route_key="/getallbusstops",
            ttl_seconds=ROUTE_CACHE_TTLS["/getallbusstops"],
            generator=build_payload,
        )
    
    except HTTPException as exc:
        emit_route_http_error("/getallbusstops", request, exc, t0, stage=stage)
        raise
    except Exception as exc:
        print(f"Error retrieving bus stops: {exc}")
        emit_route_exception("/getallbusstops", request, exc, t0, stage=stage)
        raise HTTPException(status_code=500, detail="Failed to retrieve bus stops")

@busStops_router.get("/bustiming")
async def get_bus_timing(
    request: Request,
    busstopcode: str = Query(..., regex=r'^\d{5}$'),
    busservicenos: str = Query(...),
    userID: Optional[str] = None,
    background_tasks: BackgroundTasks = None
):
    t0 = time.perf_counter()
    requested = set(busservicenos.split(',')) - {''}
    if not requested:
        raise HTTPException(400, "No bus services specified")

    process_all = "all" in requested

    async with _sem:
        try:
            t_api_start = time.perf_counter()

            try:
                response = await _cache.get_or_fetch(
                    key=busstopcode,
                    fetch_fn=lambda: queryAPI(
                        "ltaodataservice/v3/BusArrival",
                        {"BusStopCode": busstopcode}
                    )
                )
            except HTTPException:
                raise
            except Exception as exc:
                emit_exception_log(
                    "error",
                    "cache_internal_error_bypass",
                    exc,
                    route="/bustiming",
                    bus_stop=busstopcode,
                    user_agent=request.headers.get("User-Agent", "unknown"),
                )
                response = await queryAPI(
                    "ltaodataservice/v3/BusArrival",
                    {"BusStopCode": busstopcode}
                )

            t_api_end = time.perf_counter()

            services = response.get("Services", [])
            if not services:
                total_time = time.perf_counter() - t0
                api_ms = round((t_api_end - t_api_start) * 1000, 2)
                _log_bustiming_event(
                    "info",
                    "empty_response",
                    bus_stop=busstopcode,
                    total_ms=round(total_time * 1000, 2),
                    api_ms=api_ms,
                    cache_hit=api_ms < 1.0,
                    empty_response=True,
                    user_agent=request.headers.get("User-Agent", "unknown"),
                )
                return []

            t_process_start = time.perf_counter()
            current_time = datetime.now(SINGAPORE_TZ)

            results = [
                process_bus_service(s, current_time)
                for s in services
                if (no := s.get("ServiceNo")) and (process_all or no in requested)
            ]

            t_process_end = time.perf_counter()

            t_sort_start = time.perf_counter()
            valid = sorted(
                (r for r in results if r),
                key=lambda x: service_sort_key(x["serviceNo"])
            )
            t_sort_end = time.perf_counter()

            total_time = time.perf_counter() - t0
            api_ms = (t_api_end - t_api_start) * 1000

            _log_bustiming_event(
                "info",
                "success",
                bus_stop=busstopcode,
                total_ms=round(total_time * 1000, 2),
                api_ms=round(api_ms, 2),
                cache_hit=api_ms < 1.0,
                process_ms=round((t_process_end - t_process_start) * 1000, 2),
                sort_ms=round((t_sort_end - t_sort_start) * 1000, 2),
                user_agent=request.headers.get("User-Agent", "unknown"),
            )

            return valid

        except HTTPException as exc:
            _log_bustiming_event(
                "warning" if exc.status_code < 500 else "error",
                "http_error",
                bus_stop=busstopcode,
                status_code=exc.status_code,
                detail=exc.detail,
                total_ms=round((time.perf_counter() - t0) * 1000, 2),
                user_agent=request.headers.get("User-Agent", "unknown"),
            )
            raise
        except Exception as exc:
            emit_exception_log(
                "error",
                "unhandled_error",
                exc,
                route="/bustiming",
                bus_stop=busstopcode,
                total_ms=round((time.perf_counter() - t0) * 1000, 2),
                user_agent=request.headers.get("User-Agent", "unknown"),
            )
            raise HTTPException(500, "Service unavailable")
