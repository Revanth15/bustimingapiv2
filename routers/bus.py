from fastapi import APIRouter, HTTPException
from routers.database import getDBClient
from routers.utils import getBusRoutesFromLTA ,getFormattedBusRoutesData

dbClient = getDBClient()

bus_router = APIRouter()

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