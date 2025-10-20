from datetime import datetime, timedelta, timezone
import sys
from fastapi import APIRouter, HTTPException
from routers.database import createRequest, getDBClient,updateUserDetails
from routers.utils import process_bus_service, queryAPI, natural_sort_key
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

async def _run_in_batches(func, items, batch_size=100, delay=0.01):
    results = []
    for i in range(0, len(items), batch_size):
        batch = items[i:i+batch_size]
        batch_results = []
        for item in batch:
            try:
                res = await asyncio.to_thread(func, item)
                batch_results.append(res)
                await asyncio.sleep(delay)
            except Exception as e:
                batch_results.append(e)
        results.extend(batch_results)
        logger.info(f"Processed batch {i}-{i+len(batch)-1}")
    return results

@busStops_router.get("/extractbusstops")
async def extract_bus_stops():
    """
    Extract bus stop data from the external API and store/update it in PocketBase.
    """
    counter = 0
    flatten = lambda l: [y for x in l for y in x]

    try:
        # Get all existing bus stops
        logger.info("Fetching existing bus stops from PocketBase...")
        existing_busstops = dbClient.collection("busstops").get_full_list()
        existing_busstop_master_list = dbClient.collection("jsons").get_one("busStopAvailableServicesUpdated")

        # Map: busStopCode -> record
        bus_stop_map = {stop.id: stop for stop in existing_busstops}
        bus_stop_master_list = existing_busstop_master_list.__dict__["json_value"]

    except Exception as e:
        print(f"Error checking PocketBase: {e}")
        raise HTTPException(status_code=500, detail="Failed to check existing bus stops")

    try:
        # Fetch bus stops from API
        logger.info("Fetching bus stops from LTA API...")
        results = []
        while True:
            result = await queryAPI("ltaodataservice/BusStops", {"$skip": str(counter)})
            results.append(result)
            counter += 500
            logger.debug(f"Fetched {len(result.get('value', []))} bus stops at offset {counter}")
            if counter >= 10000:
                break

        # Flatten results
        data_list = flatten([res["value"] for res in results if res.get("value")])
        logger.info(f"Fetched total {len(data_list)} bus stops from API")

        new_busstops = []
        updated_busstops = []

        for stop in data_list:
            stop_id = stop["BusStopCode"]
            bus_services = ",".join(map(str, bus_stop_master_list.get(stop_id, [])))

            new_data = {
                "id": stop_id,
                "description": stop["Description"],
                "latitude": stop["Latitude"],
                "longitude": stop["Longitude"],
                "road_name": stop["RoadName"],
                "bus_services": bus_services
            }

            if stop_id not in bus_stop_map:
                # New bus stop
                new_busstops.append(new_data)
            else:
                # Compare with existing record
                existing = bus_stop_map[stop_id]
                existing_data = {
                    "description": existing.description,
                    "latitude": existing.latitude,
                    "longitude": existing.longitude,
                    "road_name": existing.road_name,
                    "bus_services": existing.bus_services,
                }

                if existing_data != {k: v for k, v in new_data.items() if k != "id"}:
                    updated_busstops.append(new_data)

        logger.info(f"{len(new_busstops)} new bus stops to insert")
        logger.info(f"{len(updated_busstops)} existing bus stops to update")

        if new_busstops:
            logger.info("Creating new bus stops (batched)...")
            # func for create expects a dict
            def _create_func(data):
                return dbClient.collection("busstops").create(data)

            create_results = await _run_in_batches(_create_func, new_busstops, batch_size=50)
            for i, res in enumerate(create_results):
                if isinstance(res, Exception):
                    logger.error(f"Failed to create {new_busstops[i]['id']}: {res}")
                else:
                    logger.debug(f"Created {new_busstops[i]['id']}")

        # === Update changed bus stops in batches ===
        if updated_busstops:
            logger.info("Updating existing bus stops (batched)...")
            # wrapper to match _run_in_batches signature: expects single arg
            def _update_func(payload):
                _id, data = payload["id"], payload
                return dbClient.collection("busstops").update(_id, data)

            update_payloads = updated_busstops  # each item contains id and fields
            update_results = await _run_in_batches(_update_func, update_payloads, batch_size=50)
            for i, res in enumerate(update_results):
                if isinstance(res, Exception):
                    logger.error(f"Failed to update {update_payloads[i]['id']}: {res}")
                else:
                    logger.debug(f"Updated {update_payloads[i]['id']}")

        logger.info("Bus stop extraction & update completed successfully")

        return {
            "message": f"Bus stops processed successfully",
            "new": len(new_busstops),
            "updated": len(updated_busstops)
        }

    except Exception as e:
        print(f"Error storing bus stops: {e}")
        raise HTTPException(status_code=500, detail="Failed to extract and store bus stops")


@busStops_router.get("/getallbusstops")
async def get_all_bus_stops():
    """
    Retrieve all bus stop information stored in PocketBase.
    """
    try:
        bus_stops = dbClient.collection("busstops").get_full_list(2500)
        
        bus_stop_data = [{
            "id": stop.id,
            "description": stop.description,
            "latitude": stop.latitude,
            "longitude": stop.longitude,
            "road_name": stop.road_name,
            "bus_services": stop.bus_services
        } for stop in bus_stops]

        return {"busStops": bus_stop_data}
    
    except Exception as e:
        print(f"Error retrieving bus stops: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve bus stops")

@busStops_router.get("/bustiming")
async def get_bus_timing(busstopcode: str, busservicenos: str, userID: Optional[str] = None):
    if not busstopcode.isdigit() or len(busstopcode) != 5:
         raise HTTPException(status_code=400, detail="Invalid BusStopCode format.")

    requestedBusList = {i for i in busservicenos.split(',') if i}
    process_all = "all" in requestedBusList

    current_time_sg = datetime.now(SINGAPORE_TZ)

    try:
        ltaResponse = await queryAPI("ltaodataservice/v3/BusArrival", {"BusStopCode": busstopcode})

        busServices = ltaResponse.get("Services", [])
        if not busServices:
             return []

        tasks = []
        for busService in busServices:
            service_no = busService.get("ServiceNo")
            if service_no and (process_all or service_no in requestedBusList):
                tasks.append(process_bus_service(busService, current_time_sg))

        if not tasks:
            return []

        results = await asyncio.gather(*tasks)

        valid_results = [res for res in results if res]

        sorted_data = sorted(valid_results, key=lambda x: natural_sort_key(x["serviceNo"]))

        # Background tasks for non-critical I/O
        if userID is not None:
            asyncio.create_task(createRequest(busstopcode, busservicenos, userID))
            asyncio.create_task(updateUserDetails(userID))

        return sorted_data

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print(f"Error retrieving bus service timing for stop {busstopcode}: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving bus service timing: {e}")