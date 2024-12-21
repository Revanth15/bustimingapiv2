import datetime
import os
from fastapi import APIRouter, HTTPException, Query
from pocketbase import PocketBase
from dotenv import load_dotenv
from routers.schemas import BusTimingRequest, User
from routers.utils import getBusArrivalDetails, queryAPI, getEnvVariable

load_dotenv()

db_router = APIRouter()

ACCOUNT_KEY = getEnvVariable("ACCOUNT_KEY")
POCKETBASE_URL = getEnvVariable("POCKETBASE_URL")

client = PocketBase(POCKETBASE_URL)

admin_data = client.admins.auth_with_password(os.getenv("ADMIN_USERNAME"), os.getenv("ADMIN_PASSWORD"))
print(admin_data.is_valid)

# Utility function to create a user
def create_dbuser(data: dict):
    try:
        dbuser = client.collection("users").create(data)
        if dbuser.id:
            dbuser_details = client.collection("userDetails").create({
                "num_requests" : 0,
                "days_active" : 1,
                "field": dbuser.id
            })
        return dbuser
    except Exception as e:
        print(f"Error creating user: {e}")
        raise HTTPException(status_code=500, detail="Failed to create user")


# Utility function to fetch a user by ID
def get_dbuser(id: str):
    try:
        dbuser = client.collection("users").get_one(id=id)
        return dbuser
    except Exception as e:
        print(f"Error fetching user: {e}")
        raise HTTPException(status_code=404, detail="User not found")
    




# FastAPI route to create a user
@db_router.post("/user")
async def create_user(user_data: User):
    try:
        # Validate passwords
        # User.validate_passwords(user_data.password, user_data.passwordConfirm)

        # Convert Pydantic model to dictionary
        user_dict = user_data.dict()
        user = create_dbuser(user_dict)
        return user
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# FastAPI route to fetch a user by ID
@db_router.get("/user")
async def get_user(id: str = Query(..., description="The ID of the user to fetch")):
    try:
        user = get_dbuser(id)
        return user
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    

@db_router.get("/extractbusstops")
async def extract_bus_stops():
    """
    Extract bus stop data from the external API and store it in PocketBase.
    """
    counter = 0
    data_list = []
    flatten = lambda l: [y for x in l for y in x]

    # Check if bus stops are already extracted
    try:
        existing_busstops = client.collection("busstops").get_full_list()
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
                client.collection("busstops").create(new_busstop)
                
        return {"message": "Bus stops extracted and stored successfully"}
    except Exception as e:
        print(f"Error storing bus stops: {e}")
        raise HTTPException(status_code=500, detail="Failed to extract and store bus stops")

@db_router.get("/bustiming")
async def get_bus_timing(busTimingReq: BusTimingRequest):
    requestedBusList = busTimingReq.busservicenos.split(',')
    requestedBusList = [i for i in requestedBusList if i]
    try:
         while True: 
            # ltaResponse = {
            #         "odata.metadata": "http://datamall2.mytransport.sg/ltaodataservice/$metadata#BusArrivalv2/@Element",
            #         "BusStopCode": "57121",
            #         "Services": [
            #             {
            #                 "ServiceNo": "167",
            #                 "Operator": "TTS",
            #                 "NextBus": {
            #                     "OriginCode": "10009",
            #                     "DestinationCode": "58009",
            #                     "EstimatedArrival": "2024-12-21T18:24:41+08:00",
            #                     "Latitude": "1.3774783333333334",
            #                     "Longitude": "103.82823783333333",
            #                     "VisitNumber": "1",
            #                     "Load": "SDA",
            #                     "Feature": "WAB",
            #                     "Type": "SD"
            #                 },
            #                 "NextBus2": {
            #                     "OriginCode": "10009",
            #                     "DestinationCode": "58009",
            #                     "EstimatedArrival": "2024-12-21T18:47:24+08:00",
            #                     "Latitude": "1.3145793333333333",
            #                     "Longitude": "103.84060866666667",
            #                     "VisitNumber": "1",
            #                     "Load": "SDA",
            #                     "Feature": "WAB",
            #                     "Type": "SD"
            #                 },
            #                 "NextBus3": {
            #                     "OriginCode": "",
            #                     "DestinationCode": "",
            #                     "EstimatedArrival": "",
            #                     "Latitude": "",
            #                     "Longitude": "",
            #                     "VisitNumber": "",
            #                     "Load": "",
            #                     "Feature": "",
            #                     "Type": ""
            #                 }
            #             },
            #             {
            #                 "ServiceNo": "856",
            #                 "Operator": "TTS",
            #                 "NextBus": {
            #                     "OriginCode": "59009",
            #                     "DestinationCode": "46009",
            #                     "EstimatedArrival": "2024-12-21T18:15:26+08:00",
            #                     "Latitude": "0.0",
            #                     "Longitude": "0.0",
            #                     "VisitNumber": "1",
            #                     "Load": "SEA",
            #                     "Feature": "WAB",
            #                     "Type": "SD"
            #                 },
            #                 "NextBus2": {
            #                     "OriginCode": "59009",
            #                     "DestinationCode": "46009",
            #                     "EstimatedArrival": "2024-12-21T18:25:06+08:00",
            #                     "Latitude": "0.0",
            #                     "Longitude": "0.0",
            #                     "VisitNumber": "1",
            #                     "Load": "SEA",
            #                     "Feature": "WAB",
            #                     "Type": "DD"
            #                 },
            #                 "NextBus3": {
            #                     "OriginCode": "59009",
            #                     "DestinationCode": "46009",
            #                     "EstimatedArrival": "2024-12-21T18:35:06+08:00",
            #                     "Latitude": "0.0",
            #                     "Longitude": "0.0",
            #                     "VisitNumber": "1",
            #                     "Load": "SEA",
            #                     "Feature": "WAB",
            #                     "Type": "DD"
            #                 }
            #             },
            #             {
            #                 "ServiceNo": "858",
            #                 "Operator": "TTS",
            #                 "NextBus": {
            #                     "OriginCode": "46009",
            #                     "DestinationCode": "46009",
            #                     "EstimatedArrival": "2024-12-21T18:07:56+08:00",
            #                     "Latitude": "1.433629",
            #                     "Longitude": "103.82634466666667",
            #                     "VisitNumber": "1",
            #                     "Load": "SEA",
            #                     "Feature": "WAB",
            #                     "Type": "SD"
            #                 },
            #                 "NextBus2": {
            #                     "OriginCode": "46009",
            #                     "DestinationCode": "46009",
            #                     "EstimatedArrival": "2024-12-21T18:15:04+08:00",
            #                     "Latitude": "1.4298153333333334",
            #                     "Longitude": "103.83526083333334",
            #                     "VisitNumber": "1",
            #                     "Load": "SDA",
            #                     "Feature": "WAB",
            #                     "Type": "SD"
            #                 },
            #                 "NextBus3": {
            #                     "OriginCode": "46009",
            #                     "DestinationCode": "46009",
            #                     "EstimatedArrival": "2024-12-21T18:19:24+08:00",
            #                     "Latitude": "1.424226",
            #                     "Longitude": "103.8368645",
            #                     "VisitNumber": "1",
            #                     "Load": "SEA",
            #                     "Feature": "WAB",
            #                     "Type": "SD"
            #                 }
            #             },
            #             {
            #                 "ServiceNo": "859",
            #                 "Operator": "TTS",
            #                 "NextBus": {
            #                     "OriginCode": "58009",
            #                     "DestinationCode": "58009",
            #                     "EstimatedArrival": "2024-12-21T18:38:50+08:00",
            #                     "Latitude": "1.447356",
            #                     "Longitude": "103.82233383333333",
            #                     "VisitNumber": "1",
            #                     "Load": "SEA",
            #                     "Feature": "WAB",
            #                     "Type": "SD"
            #                 },
            #                 "NextBus2": {
            #                     "OriginCode": "58009",
            #                     "DestinationCode": "58009",
            #                     "EstimatedArrival": "2024-12-21T18:47:47+08:00",
            #                     "Latitude": "1.4525755",
            #                     "Longitude": "103.81712733333333",
            #                     "VisitNumber": "1",
            #                     "Load": "SEA",
            #                     "Feature": "WAB",
            #                     "Type": "SD"
            #                 },
            #                 "NextBus3": {
            #                     "OriginCode": "",
            #                     "DestinationCode": "",
            #                     "EstimatedArrival": "",
            #                     "Latitude": "",
            #                     "Longitude": "",
            #                     "VisitNumber": "",
            #                     "Load": "",
            #                     "Feature": "",
            #                     "Type": ""
            #                 }
            #             },
            #             {
            #                 "ServiceNo": "969",
            #                 "Operator": "TTS",
            #                 "NextBus": {
            #                     "OriginCode": "75009",
            #                     "DestinationCode": "46009",
            #                     "EstimatedArrival": "2024-12-21T18:16:34+08:00",
            #                     "Latitude": "1.4293636666666667",
            #                     "Longitude": "103.83521733333333",
            #                     "VisitNumber": "1",
            #                     "Load": "SEA",
            #                     "Feature": "WAB",
            #                     "Type": "DD"
            #                 },
            #                 "NextBus2": {
            #                     "OriginCode": "75009",
            #                     "DestinationCode": "46009",
            #                     "EstimatedArrival": "2024-12-21T18:30:10+08:00",
            #                     "Latitude": "1.3962421666666667",
            #                     "Longitude": "103.85012583333334",
            #                     "VisitNumber": "1",
            #                     "Load": "SDA",
            #                     "Feature": "WAB",
            #                     "Type": "DD"
            #                 },
            #                 "NextBus3": {
            #                     "OriginCode": "75009",
            #                     "DestinationCode": "46009",
            #                     "EstimatedArrival": "2024-12-21T18:40:07+08:00",
            #                     "Latitude": "1.395098",
            #                     "Longitude": "103.90568483333334",
            #                     "VisitNumber": "1",
            #                     "Load": "SEA",
            #                     "Feature": "WAB",
            #                     "Type": "DD"
            #                 }
            #             },
            #             {
            #                 "ServiceNo": "980",
            #                 "Operator": "TTS",
            #                 "NextBus": {
            #                     "OriginCode": "80009",
            #                     "DestinationCode": "58009",
            #                     "EstimatedArrival": "2024-12-21T18:14:59+08:00",
            #                     "Latitude": "1.4132685",
            #                     "Longitude": "103.8229775",
            #                     "VisitNumber": "1",
            #                     "Load": "SEA",
            #                     "Feature": "WAB",
            #                     "Type": "SD"
            #                 },
            #                 "NextBus2": {
            #                     "OriginCode": "80009",
            #                     "DestinationCode": "58009",
            #                     "EstimatedArrival": "2024-12-21T18:29:41+08:00",
            #                     "Latitude": "1.3688636666666667",
            #                     "Longitude": "103.8283345",
            #                     "VisitNumber": "1",
            #                     "Load": "SDA",
            #                     "Feature": "WAB",
            #                     "Type": "SD"
            #                 },
            #                 "NextBus3": {
            #                     "OriginCode": "80009",
            #                     "DestinationCode": "58009",
            #                     "EstimatedArrival": "2024-12-21T18:46:06+08:00",
            #                     "Latitude": "1.3262511666666668",
            #                     "Longitude": "103.84174616666667",
            #                     "VisitNumber": "1",
            #                     "Load": "SDA",
            #                     "Feature": "WAB",
            #                     "Type": "SD"
            #                 }
            #             }
            #         ]
            #     }
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
            return returnReponse
    except Exception as e:
        print(f"Error retrieving bus service timing: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving bus service timing")