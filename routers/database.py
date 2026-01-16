from datetime import datetime, timezone
import os
from fastapi import APIRouter, HTTPException, Query
from pocketbase import PocketBase
from dotenv import load_dotenv
from routers.schemas import BusTimingRequest, User
from routers.utils import queryAPI, getEnvVariable, timeDifferenceToNowSg
from supabase import create_client, Client

load_dotenv()

db_router = APIRouter()

SUPABASE_URL = getEnvVariable("SUPABASE_URL")
SUPABASE_API_KEY = getEnvVariable("SUPABASE_API_KEY")
SUPABASE_EMAIL = getEnvVariable("SUPABASE_EMAIL")
SUPABASE_PASSWORD = getEnvVariable("SUPABASE_PASSWORD")

supabase = create_client(SUPABASE_URL,SUPABASE_API_KEY)

supabase.auth.sign_in_with_password(
    {
        "email": SUPABASE_EMAIL,
        "password": SUPABASE_PASSWORD
    }
)

def getDBClient():
    return supabase

# Utility function to create a user
def create_dbuser(data: dict):
    return {}
    # try:
    #     userDetails = client.collection("userDetails").create({
    #             "num_requests" : 0,
    #             "days_active" : 1,
    #         })
    #     if userDetails.id:
    #         data["userDetails"] = userDetails.id
    #         dbuser = client.collection("users").create(data)
    #     return dbuser
    # except Exception as e:
    #     print(f"Error creating user: {e}")
    #     raise HTTPException(status_code=500, detail="Failed to create user")


# Utility function to fetch a user by ID
def get_dbuser(userID: str):
    return {}
    # try:
    #     dbuser = client.collection("users").get_one(userID, { "expand" : "userDetails"})
    #     return dbuser
    # except Exception as e:
    #     print(f"Error fetching user: {e}")
    #     raise HTTPException(status_code=404, detail="User not found")

# Update user details, increment days active & num of requests
def updateUserDetails(userID: str):
    return {}
    # try:
    #     dbUser = get_dbuser(userID)
    #     if dbUser.id:
    #         userDetails = dbUser.__dict__["expand"]["userDetails"]
    #         days_active = userDetails.days_active
    #         num_requests = userDetails.num_requests + 1
    #         if userDetails.updated.date() < datetime.now(timezone.utc).date():
    #             days_active += 1
    #         dbuser_details = client.collection("userDetails").update(userDetails.id,{
    #             "num_requests" : num_requests,
    #             "days_active" : days_active,
    #         })
    #         return dbuser_details
    # except Exception as e:
    #     print(f"Error updating user details: {e}")
    #     raise HTTPException(status_code=500, detail="Failed to update user details")

# Create a request in db
def createRequest(busStopCode: int, busServiceNos: str, userID: str):
    return {}
    # try:
    #     dbRequest = client.collection("requests").create({
    #         "busStopCode": busStopCode,
    #         "serviceNo": busServiceNos,
    #         "userID": userID,
    #     })
    #     return dbRequest
    # except Exception as e:
    #     print(f"Error creating request: {e}")
    #     raise HTTPException(status_code=404, detail=str(e))