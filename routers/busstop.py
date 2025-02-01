from fastapi import APIRouter, HTTPException
from routers.database import createRequest, getDBClient,updateUserDetails
from routers.schemas import BusTimingRequest
from routers.utils import getBusArrivalDetails, queryAPI

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
        existing_busstops = dbClient.collection("busstops").get_full_list()
        if existing_busstops:
            bus_stop_codes = list(map(lambda stop: stop.id, existing_busstops))
            # return {"message": "Bus stops already extracted"}
            print(f"{len(bus_stop_codes)} Bus stops already extracted")
    except Exception as e:
        print(f"Error checking PocketBase: {e}")
        raise HTTPException(status_code=500, detail="Failed to check existing bus stops")

    # Fetch and store bus stops
    try:
        while True:
            res = queryAPI("ltaodataservice/BusStops", {"$skip": str(counter)})

            if len(res["value"]) == 0:
                break

            data_list.append(res["value"])
            counter += 500
        data_list = flatten(data_list)

        if len(data_list) == len(bus_stop_codes):
            return {"message": "Bus stops already extracted"}

        # Store bus stops in PocketBase
        for stop in data_list:
            if stop["BusStopCode"] not in bus_stop_codes:
                new_busstop = {
                    "id": stop["BusStopCode"],
                    "description": stop["Description"],
                    "latitude": stop["Latitude"],
                    "longitude": stop["Longitude"],
                    "road_name": stop["RoadName"],
                }
                print(new_busstop["id"], new_busstop["road_name"], new_busstop["description"])
                dbClient.collection("busstops").create(new_busstop)
                
        return {"message": "Bus stops extracted and stored successfully"}
    except Exception as e:
        print(f"Error storing bus stops: {e}")
        raise HTTPException(status_code=500, detail="Failed to extract and store bus stops")

@busStops_router.get("/bustiming")
async def get_bus_timing(busTimingReq: BusTimingRequest):
    requestedBusList = busTimingReq.busservicenos.split(',')
    requestedBusList = [i for i in requestedBusList if i]
    try:
         while True: 
            ltaResponse = queryAPI(f"ltaodataservice/BusArrivalv2?BusStopCode={busTimingReq.busstopcode}", {})
            busServices = ltaResponse["Services"]
            returnReponse = []
            if requestedBusList[0] == "all":
                for busService in busServices:
                    busArrivalTime = getBusArrivalDetails(busService)
                    returnReponse.append({
                        "serviceNo" : busService["ServiceNo"],
                        "serviceDetails": busArrivalTime
                    })
            else:
                for busService in busServices:
                    if busService["ServiceNo"] in requestedBusList:
                        busArrivalTime = getBusArrivalDetails(busService)
                        returnReponse.append({
                            "serviceNo" : busService["ServiceNo"],
                            "serviceDetails": busArrivalTime
                        })

            createRequest(busTimingReq.busstopcode, busTimingReq.busservicenos,busTimingReq.userID)
            updateUserDetails(busTimingReq.userID)
            return returnReponse
    except Exception as e:
        print(f"Error retrieving bus service timing: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving bus service timing")