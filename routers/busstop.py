from datetime import datetime, timedelta, timezone
import gzip
import json
import sys
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Response
from fastapi.responses import JSONResponse
import pytz
from routers.database import createRequest, getDBClient,updateUserDetails
from routers.utils import cache_headers, compress_to_gzip, process_bus_service, queryAPI, natural_sort_key, service_sort_key
import asyncio
from typing import Optional
import logging

logger = logging.getLogger()

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

@busStops_router.get("/extractBusStops")
async def extract_bus_stops():
    """
    Extract bus stop data from the LTA API and store/update in Supabase.
    - Fetches bus stops from LTA API in batches.
    - Uses bus_stop_master_list from jsons table for bus_services.
    - Upserts into bus_stops table with id as BusStopCode (TEXT).
    - Includes modified_at timestamp in SGT (GMT+8).
    """
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
        stored_busstops = dbClient.table("bus_stops").select("id", count="exact").execute()
        logger.info(f"Total stored bus stops: {stored_busstops.count}")

        return {
            "message": "Bus stops processed successfully",
            "new": len(new_busstops),
            "updated": len(updated_busstops)
        }

    except Exception as e:
        logger.error(f"Error processing bus stops: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@busStops_router.get("/getallbusstops")
async def get_all_bus_stops():
    """
    Retrieve all bus stop information stored in PocketBase.
    """
    try:
        response = dbClient.table("bus_stops").select("id, description, latitude, longitude, road_name, bus_services").execute()
        bus_stop_data = []
        for stop in response.data:
            bus_stop_data.append({
                "id": stop["id"],
                "description": stop["description"],
                "latitude": stop["latitude"],
                "longitude": stop["longitude"],
                "road_name": stop["road_name"],
                "bus_services": stop["bus_services"]
            })

        # return {"busStops": bus_stop_data}
        # full_structure = {"busStops": bus_stop_data}
        # json_string = json.dumps(full_structure, separators=(',', ':'))
        # json_bytes = json_string.encode("utf-8")
        # compressed_data = gzip.compress(json_bytes)

        # return Response(
        #     content=compressed_data,
        #     media_type="application/json",
        #     headers={
        #         **cache_headers(),
        #         "Content-Encoding": "gzip"
        #     }
        # )
        return JSONResponse(content={"busStops": bus_stop_data}, headers=cache_headers())
    
    except Exception as e:
        print(f"Error retrieving bus stops: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve bus stops")

@busStops_router.get("/bustiming")
async def get_bus_timing(
    busstopcode: str = Query(..., regex=r'^\d{5}$'),
    busservicenos: str = Query(...),
    userID: Optional[str] = None,
    background_tasks: BackgroundTasks = None
):
    requested = set(busservicenos.split(',')) - {''}
    if not requested:
        raise HTTPException(400, "No bus services specified")
    
    process_all = "all" in requested
    
    try:
        response = await queryAPI("ltaodataservice/v3/BusArrival", {"BusStopCode": busstopcode})
        services = response.get("Services", [])
        
        if not services:
            return []
        
        current_time = datetime.now(SINGAPORE_TZ)
        
        results = await asyncio.gather(*[
            process_bus_service(s, current_time)
            for s in services
            if (no := s.get("ServiceNo")) and (process_all or no in requested)
        ])
        
        # Filter None and sort
        valid = sorted(
            (r for r in results if r),
            key=lambda x: service_sort_key(x["serviceNo"])
        )

        # Background tasks for non-critical I/O
        # if userID is not None:
        #     asyncio.create_task(createRequest(busstopcode, busservicenos, userID))
        #     asyncio.create_task(updateUserDetails(userID))
        
        return valid
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error: {busstopcode} - {e}", file=sys.stderr)
        raise HTTPException(500, "Service unavailable")