from datetime import datetime
import json
from typing import List, Optional
import uuid
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
import httpx
from pydantic import BaseModel
import pytz
from routers.database import getDBClient
from routers.utils import cache_headers, compress_to_gzip, getBusRoutesFromLTA, getBusServicesFromLTA ,getFormattedBusRoutesData, map_bus_services, queryAPI, restructure_to_stops_only
import gzip

dbClient = getDBClient()

bus_router = APIRouter()

class DeleteRequest(BaseModel):
    serviceNumbers: list[str]

    
GEOJSON_URL = "https://data.busrouter.sg/v1/routes.min.geojson"

class PolylineRequest(BaseModel):
    serviceNumbers: list[str]

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
async def extract_bus_routes_raw_data():
    try:
        bus_route_key = "busRouteRaw"
        raw_data = await getBusRoutesFromLTA()
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
        response = dbClient.table("bus_route_raw").upsert(
            formatted_data,
            on_conflict="id"  # Update if id already exists
        ).execute()

        # # Check if the operation was successful
        if not response.data:
            raise HTTPException(status_code=500, detail="Failed to store bus routes data in Supabase")

        return {"message": "Extracted and stored successfully"}

    except Exception as e:
        print(f"Error processing bus routes data: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@bus_router.get("/bus-routes/stops")
async def get_bus_routes_by_stops():
    """
    Get bus routes data organized by bus stops only.
    """
    try:
        response = dbClient.table("bus_route_raw").select("bus_stop_code, json_value").execute()

        if not response.data:
            return {"message": "No records available"}

        combined_data = {
            row["bus_stop_code"]: json.loads(row["json_value"]) 
            for row in response.data
        }

        compressed_data = compress_to_gzip(combined_data)

        return Response(
            content=compressed_data,
            media_type="application/json",
            headers={
                **cache_headers(),
                "Content-Encoding": "gzip",
                "X-Original-Size": str(len(json.dumps(combined_data))) 
            }
        )

    except Exception as e:
        print(f"Error fetching bus route data: {e}")
        raise HTTPException(status_code=500, detail="Error fetching bus route data")

@bus_router.get("/extractBusRoutesData")
async def extract_bus_stops():
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
        formatted_bus_route_data, formatted_bus_stop_available_services = getFormattedBusRoutesData(raw_bus_route_data)

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
        response = dbClient.table("jsons").upsert(
            [formatted_bus_stop_services],
            on_conflict="id"
        ).execute()

        # Check if the operation was successful
        if not response.data:
            raise HTTPException(status_code=500, detail="Failed to upsert bus stop available services data")

        return {"message": formatted_bus_route_data}

    except Exception as e:
        print(f"Error processing bus routes data: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")
    
@bus_router.get("/getBusRoutesData")
async def get_bus_route_data():
    key = "busRoute"
    try:
        response = dbClient.table("bus_route").select("service_no, json_value").execute()

        if not response.data:
            return {"message": "No records available"}
        combined_data = []

        for row in response.data:
            json_value = row["json_value"]
            data = json.loads(json_value) if isinstance(json_value, str) else json_value
            combined_data.append(data)
        

        json_data = json.dumps(combined_data).encode("utf-8")
        compressed_data = gzip.compress(json_data)

        return Response(
            content=compressed_data,
            media_type="application/json",
            headers={
                **cache_headers(),
                "Content-Encoding": "gzip"
            }
        )
    except Exception as e:
        print(f"Error fetching bus route data: {e}")
        raise HTTPException(status_code=500, detail="Error fetching bus route data")
    
@bus_router.get("/getBusStopAvailableBussesData")
async def get_bus_stop_available_busses_data():
    key = "busStopAvailableServices"
    try:
        response = dbClient.table("jsons").select("json_value").eq("id", key).execute()
        if response.data:
            return response.data[0]["json_value"]
        else:
            return {"message": "No records available"}
    except Exception as e:
        print(f"Error fetching bus stop available busses data: {e}")
        raise HTTPException(status_code=500, detail="Error fetching bus stop available busses data")
    
@bus_router.get("/getBusServicesData")
async def get_bus_services_data(overwrite: Optional[bool] = False):
    print(overwrite)
    pbKey = "busServices"

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
                busServices = await getBusServicesFromLTA()
                if not busServices:
                    return []
                camelcased_bus_services = map_bus_services(busServices)
                formatted_bus_stop_services = {
                    "id": pbKey,
                    "json_value": json.dumps(camelcased_bus_services),
                    "modified_at": current_timestamp
                }

                # Upsert bus stop available services
                response = dbClient.table("jsons").upsert(
                    [formatted_bus_stop_services],
                    on_conflict="id"
                ).execute()
                return camelcased_bus_services

        else:
            # Overwrite or fetch, map, and save to DB
            busServices = await getBusServicesFromLTA()
            if not busServices:
                return []
            camelcased_bus_services = map_bus_services(busServices)
            formatted_bus_stop_services = {
                "id": pbKey,
                "json_value": json.dumps(camelcased_bus_services),
                "modified_at": current_timestamp
            }

            # Upsert bus stop available services
            response = dbClient.table("jsons").upsert(
                [formatted_bus_stop_services],
                on_conflict="id"
            ).execute()
            return camelcased_bus_services

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print(f"Error retrieving bus services: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving bus services: {e}")
    

class BusRoute(BaseModel):
    serviceNo: str
    routes: List[dict]

class BusRouteBulkUpdate(BaseModel):
    bus_routes: List[BusRoute]

@bus_router.post("/bulkUpdateBusRoutes")
async def bulk_update_bus_routes(data: BusRouteBulkUpdate):
    """
    Bulk update bus routes data in Supabase.
    - Accepts a list of bus route objects with updated polyline values.
    - Upserts into bus_route table based on service_no.
    - Updates json_value and modified_at (SGT) for existing rows.
    - Inserts new rows with new UUIDs for id.
    """
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

    except Exception as e:
        print(f"Error processing bulk update: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@bus_router.post("/bus-routes/polylines")
async def get_bus_routes_with_polylines(request: PolylineRequest):
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
        # Swap [lng, lat] → [lat, lng]
        transformed = [[lat, lng] for lng, lat in coords]
        key = f"{service_no}|{direction}"
        if key in lookup:
            lookup[key].extend(transformed)  # concatenate multiple features
        else:
            lookup[key] = transformed

    # 2. Fetch and format LTA data
    raw_bus_route_data = await getBusRoutesFromLTA()
    formatted_bus_route_data, _ = getFormattedBusRoutesData(raw_bus_route_data)

    # 3. Filter to requested services and inject polylines
    requested = set(request.serviceNumbers)
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

@bus_router.delete("bus-routes")
async def delete_bus_routes(request: DeleteRequest):
    if not request.serviceNumbers:
        raise HTTPException(status_code=400, detail="`serviceNumbers` must be a non-empty list.")

    response = (
        dbClient.table("bus_route")
        .delete()
        .in_("service_no", request.serviceNumbers)
        .execute()
    )

    deleted = response.data or []

    return {
        "deleted": len(deleted),
        "serviceNumbers": [row["service_no"] for row in deleted],
    }