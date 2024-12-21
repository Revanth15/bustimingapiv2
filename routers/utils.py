from datetime import datetime, timedelta, timezone
import os
import requests
from dotenv import load_dotenv

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
def queryAPI(path, params):
    url = "http://datamall2.mytransport.sg/"
    headers = {
    'AccountKey': ACCOUNT_KEY
    }
    return requests.get(url + path, headers=headers,params=params).json()

def timeDifferenceToNowSg(target_time_str):
    target_time = datetime.fromisoformat(target_time_str)
    
    singapore_timezone = timezone(timedelta(hours=8))
    current_time_sg = datetime.now(singapore_timezone)
    
    time_diff = target_time - current_time_sg

    time_diff_minutes = int(time_diff.total_seconds() // 60)
    
    return time_diff_minutes

def getBusArrivalDetails(busServiceDetails):
    noOfBuses = ['NextBus','NextBus2','NextBus3']
    busArrivalDetails = []
    for key in noOfBuses:
        if busServiceDetails[key]['EstimatedArrival'] != '':
            busArrivalTime = timeDifferenceToNowSg(busServiceDetails[key]['EstimatedArrival'])
            busArrivalDetails.append(
                {
                    "busArrivalTime": busArrivalTime,
                    "busLoad": busServiceDetails[key]["Load"],
                    "busFeature": busServiceDetails[key]["Feature"],
                    "busType": busServiceDetails[key]["Type"],
                }
            )
        if key == "NextBus" and busServiceDetails[key]['EstimatedArrival'] == '':
            return {}
    return busArrivalDetails
