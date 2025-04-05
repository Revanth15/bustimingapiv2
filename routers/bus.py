from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Request
from routers.database import getDBClient
from routers.utils import getBusRoutesFromLTA ,getFormattedBusRoutesData, map_bus_services, queryAPI

dbClient = getDBClient()

bus_router = APIRouter()

@bus_router.api_route("/health", methods=["GET", "HEAD"])
async def health_check(request: Request):
    """
    Health check endpoint to ensure the API is running.
    This route will respond to both GET and HEAD requests.
    """
    if request.method == "HEAD":
        return {}
    return {"status": "API is running"}

@bus_router.get("/extractBusRoutesData")
async def extract_bus_stops():
    """
    Extract bus routes data
    """
    """
    -check if alr extracted, extract and process if not
    -do an update everyweek automatically
    """

    bus_route_key = "busRoute"
    bus_stop_available_services_key = "busStopAvailableServices"

    # Check if busRoutes are already extracted
    try:
        existingBusRoutes = dbClient.collection("jsons").get_one(bus_route_key)
        existingBusStopAvailableServicesData = dbClient.collection("jsons").get_one(bus_stop_available_services_key)

        existingBusRoutesDict = existingBusRoutes.__dict__
        existingBusStopAvailableServicesDataDict = existingBusStopAvailableServicesData.__dict__
    except Exception as e:
        print(f"Error checking PocketBase: {e}")
        raise HTTPException(status_code=500, detail="Failed to check existing bus route data")

    try:
        if not existingBusRoutesDict["json_value"] and not existingBusStopAvailableServicesDataDict["json_value"]:
            raw_bus_route_data = await getBusRoutesFromLTA()
            formatted_bus_route_data, formatted_bus_stop_available_services = getFormattedBusRoutesData(raw_bus_route_data)

            formatted_dict = [
                {
                    "id" : bus_route_key,
                    "updatingValue": {
                        "jsonValue" : formatted_bus_route_data
                    }
                },
                {
                    "id" : bus_stop_available_services_key,
                    "updatingValue": {
                        "jsonValue" : formatted_bus_stop_available_services
                    }
                }
            ]

            print(formatted_dict)


            [dbClient.collection("jsons").update(jsonData["id"], jsonData["updatingValue"]) for jsonData in formatted_dict]


            return {"message": "Extracted and stored successfully"}
        else:
            return {"message": "Already Extracted"}
            
    except Exception as e:
        print(f"Error storing bus stops: {e}")
        raise HTTPException(status_code=500, detail="Failed to extract and store bus routes data")
    
@bus_router.get("/getBusRoutesData")
async def get_bus_route_data():
    key = "busRoute"
    try:
        existingData = dbClient.collection("jsons").get_one(key)
        if existingData:
            return existingData.__dict__["json_value"]
        else:
            return {"message": "No records available"}
    except Exception as e:
        print(f"Error fetching bus route data: {e}")
        raise HTTPException(status_code=500, detail="Error fetching bus route data")
    
@bus_router.get("/getBusStopAvailableBussesData")
async def get_bus_stop_available_busses_data():
    key = "busStopAvailableServices"
    try:
        existingData = dbClient.collection("jsons").get_one(key)
        print(existingData.__dict__)
        if existingData:
            return existingData.__dict__["json_value"]
        else:
            return {"message": "No records available"}
    except Exception as e:
        print(f"Error fetching bus stop available busses data: {e}")
        raise HTTPException(status_code=500, detail="Error fetching bus stop available busses data")
    
@bus_router.get("/getBusServicesData")
async def get_bus_services_data(overwrite: Optional[bool] = False):
    print(overwrite)
    pbKey = "busServices"
    try:
        if not overwrite:
            # Get data from the database
            db_data = dbClient.collection("jsons").get_one(pbKey)
            if db_data.__dict__["json_value"]:
                return db_data.__dict__["json_value"]
            else:
                # If no data in DB, fetch from API, map, and save.
                ltaResponse = await queryAPI("ltaodataservice/BusServices", {})
                busServices = ltaResponse.get("value", [])
                if not busServices:
                    return []
                camelcased_bus_services = map_bus_services(busServices)
                data_to_save = {"jsonValue": camelcased_bus_services}
                dbClient.collection("jsons").update(pbKey, data_to_save)
                return camelcased_bus_services

        else:
            # Overwrite or fetch, map, and save to DB
            ltaResponse = await queryAPI("ltaodataservice/BusServices", {})
            busServices = ltaResponse.get("value", [])
            if not busServices:
                return []
            camelcased_bus_services = map_bus_services(busServices)
            data_to_save = {"jsonValue": camelcased_bus_services}
            dbClient.collection("jsons").update(pbKey, data_to_save)
            return camelcased_bus_services

    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        print(f"Error retrieving bus services: {e}")
        raise HTTPException(status_code=500, detail=f"Error retrieving bus services: {e}")