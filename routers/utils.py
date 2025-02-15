from datetime import datetime, timedelta, timezone
import os
import requests
from dotenv import load_dotenv
import httpx

load_dotenv()

def getEnvVariable(key: str, required: bool = True) -> str:
    """
    Fetches an environment variable and optionally ensures it is set.
    
    Args:
        key (str): The name of the environment variable.
        required (bool): Whether the variable is required (default: True).
    
    Returns:
        str: The value of the environment variable if set.
    
    Raises:
        ValueError: If the variable is required and not set.
    """
    value = os.getenv(str(key))
    if required and not value:
        raise ValueError(f"{key} is missing in the .env file")
    return value

ACCOUNT_KEY = getEnvVariable("ACCOUNT_KEY")

# Query LTA's API
async def queryAPI(path, params):
    url = "http://datamall2.mytransport.sg/" + path
    headers = {'AccountKey': ACCOUNT_KEY}
    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers=headers, params=params) 
    return response.json()

def timeDifferenceToNowSg(target_time_str):
    target_time = datetime.fromisoformat(target_time_str)
    
    singapore_timezone = timezone(timedelta(hours=8))
    current_time_sg = datetime.now(singapore_timezone)
    
    time_diff = target_time - current_time_sg

    time_diff_minutes = int(time_diff.total_seconds() // 60)
    
    return time_diff_minutes

async def process_bus_service(busService):
    busArrivalTime = getBusArrivalDetails(busService)
    if busArrivalTime:
        return {
            "serviceNo": busService["ServiceNo"],
            "serviceDetails": busArrivalTime
        }
    return None

def getBusArrivalDetails(busServiceDetails):
    noOfBuses = ['NextBus', 'NextBus2', 'NextBus3']
    busArrivalDetails = []

    for key in noOfBuses:
        estimated_arrival = busServiceDetails[key].get('EstimatedArrival', '')
        if estimated_arrival:
            busArrivalDetails.append({
                "busArrivalTime": timeDifferenceToNowSg(estimated_arrival),
                "busLoad": busServiceDetails[key]["Load"],
                "busFeature": busServiceDetails[key]["Feature"],
                "busType": busServiceDetails[key]["Type"],
            })
        else:
            busArrivalDetails.append({
                "busArrivalTime": -100, 
                "busLoad": "-",
                "busFeature": "-",
                "busType": "-"
            })
    return busArrivalDetails
