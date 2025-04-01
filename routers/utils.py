from datetime import datetime, timedelta, timezone
import os
from collections import defaultdict
from dotenv import load_dotenv
import httpx
import re

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


async def getBusRoutesFromLTA():
    results = []
    counter = 0
    flatten = lambda l: [y for x in l for y in x]
    print("Starting to fetch bus routes data...")

    while True:
        print(f"Counter value: {counter}")
        result = await queryAPI("ltaodataservice/BusRoutes", {"$skip": str(counter)})
        results.append(result)
        counter += 500
        if counter >= 30000:
            break

    flattened_list = flatten([res["value"] for res in results if res.get("value")])

    return flattened_list

# def getBusStopAvailableServicesList(busRoutes: dict):
#     bus_stop_master_list = defaultdict(list)  # BusStopCode -> List of ServiceNos
    
#     if busRoutes:
#         for service in busRoutes:
#             service_no = service.get("ServiceNo")
#             bus_stop_code = service.get("BusStopCode")

#             bus_stop_master_list[bus_stop_code].append(service_no)

#     bus_stop_master_list = dict(bus_stop_master_list)

#     return bus_stop_master_list

def getFormattedBusRoutesData(busRoutes: dict):
    bus_route_dict = []  # List of service dictionaries
    bus_stop_master_list = defaultdict(list)  # BusStopCode -> List of ServiceNos

    service_dict = {}  # Temporary dictionary to store services
    
    if busRoutes:
        for service in busRoutes:
            service_no = service.get("ServiceNo", "")
            bus_stop_code = service.get("BusStopCode", "")
            stop_sequence = service.get("StopSequence", 0)
            direction = str(service.get("Direction", 1))  # Default to 1 if no direction is specified

            if service_no not in service_dict:
                service_dict[service_no] = {"serviceNo": service_no, "routes": []}

            # Find existing entry for this direction
            route_entry = next((route for route in service_dict[service_no]["routes"] if route["direction"] == direction), None)
            
            if not route_entry:
                route_entry = {"direction": direction, "busStopIDs": [], "polyline": ""}
                service_dict[service_no]["routes"].append(route_entry)
            
            route_entry["busStopIDs"].append((stop_sequence, bus_stop_code))

            # Populate bus stop master list
            if service_no not in bus_stop_master_list[bus_stop_code]:
                bus_stop_master_list[bus_stop_code].append(service_no)

        # Sort bus stop lists in bus_stop_master_list
        for bus_stop in bus_stop_master_list:
            bus_stop_master_list[bus_stop].sort()

        # Sort and format bus stops in service_dict
        for service_no in service_dict:
            for route in service_dict[service_no]["routes"]:
                route["busStopIDs"].sort(key=lambda x: x[0])  # Sort by StopSequence
                route["busStopIDs"] = [bus_stop_code for _, bus_stop_code in route["busStopIDs"]]
    
    bus_route_dict = list(service_dict.values())  # Convert service_dict to a list
    
    return bus_route_dict, dict(bus_stop_master_list)
        

def natural_sort_key(service_no):
    match = re.match(r"(\d+)([A-Z]*)", service_no) 
    number_part = int(match.group(1))
    letter_part = match.group(2) or "" 
    return (number_part, letter_part)