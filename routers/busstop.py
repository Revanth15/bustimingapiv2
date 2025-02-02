from fastapi import APIRouter, HTTPException
from routers.database import createRequest, getDBClient,updateUserDetails
from routers.schemas import BusTimingRequest
from routers.utils import process_bus_service, queryAPI
import asyncio


dbClient = getDBClient()

busStops_router = APIRouter()

@busStops_router.get("/extractbusstops")
async def extract_bus_stops():
    """
    Extract bus stop data from the external API and store it in PocketBase.
    """
    counter = 0
    data_list = []
    flatten = lambda l: [y for x in l for y in x]

    # Check if bus stops are already extracted
    try:
        existing_busstops = await asyncio.to_thread(dbClient.collection("busstops").get_full_list)
        bus_stop_codes = {stop.id for stop in existing_busstops}
    except Exception as e:
        print(f"Error checking PocketBase: {e}")
        raise HTTPException(status_code=500, detail="Failed to check existing bus stops")

    # Fetch and store bus stops concurrently
    try:
        # Start parallel API calls for bus stops (using asyncio.gather)
        tasks = []
        while True:
            tasks.append(queryAPI("ltaodataservice/BusStops", {"$skip": str(counter)}))
            counter += 500
            if counter >= 8000:
                break

        results = await asyncio.gather(*tasks)
        
        # Flatten all the results from the API calls
        data_list = flatten([res["value"] for res in results if res.get("value")])

        if len(data_list) == len(bus_stop_codes):
            return {"message": "Bus stops already extracted"}

        new_busstops = []
        for stop in data_list:
            if stop["BusStopCode"] not in bus_stop_codes:
                new_busstops.append({
                    "id": stop["BusStopCode"],
                    "description": stop["Description"],
                    "latitude": stop["Latitude"],
                    "longitude": stop["Longitude"],
                    "road_name": stop["RoadName"],
                })
        
        if new_busstops:
            await asyncio.to_thread(lambda: [dbClient.collection("busstops").create(busstop) for busstop in new_busstops])

        return {"message": "Bus stops extracted and stored successfully"}
    
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
            "road_name": stop.road_name
        } for stop in bus_stops]

        return {"busStops": bus_stop_data}
    
    except Exception as e:
        print(f"Error retrieving bus stops: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve bus stops")

@busStops_router.get("/bustiming")
async def get_bus_timing(busTimingReq: BusTimingRequest):
    requestedBusList = [i for i in busTimingReq.busservicenos.split(',') if i]
    try:
        ltaResponse = await queryAPI("ltaodataservice/BusArrivalv2", {"BusStopCode": busTimingReq.busstopcode})
        busServices = ltaResponse.get("Services", [])
        returnResponse = []

        # Process bus timings concurrently
        if "all" in requestedBusList:
            tasks = [process_bus_service(busService) for busService in busServices]
        else:
            tasks = [
                process_bus_service(busService)
                for busService in busServices
                if busService["ServiceNo"] in requestedBusList
            ]

        results = await asyncio.gather(*tasks)
        returnResponse = [res for res in results if res]

        # Background tasks for I/O operations to increase efficiency
        # Optional data tracking if userID is present
        if busTimingReq.userID is not None:
            asyncio.create_task(asyncio.to_thread(createRequest, busTimingReq.busstopcode, busTimingReq.busservicenos, busTimingReq.userID))
            asyncio.create_task(asyncio.to_thread(updateUserDetails, busTimingReq.userID))

        return returnResponse

    except Exception as e:
        print(f"Error retrieving bus service timing: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving bus service timing")