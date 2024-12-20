import datetime
import os
from fastapi import APIRouter, HTTPException, Query
from pocketbase import PocketBase
from dotenv import load_dotenv
from routers.schemas import User
from routers.utils import queryAPI, get_env_variable

load_dotenv()

db_router = APIRouter()

ACCOUNT_KEY = get_env_variable("ACCOUNT_KEY")
POCKETBASE_URL = get_env_variable("POCKETBASE_URL")

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

