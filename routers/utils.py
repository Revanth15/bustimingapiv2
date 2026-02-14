from datetime import datetime, timedelta, timezone
import json
# import geopandas as gpd
import os
from collections import defaultdict
from typing import Any, Dict, List, Optional
from dotenv import load_dotenv
from fastapi import HTTPException
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
    url = "https://datamall2.mytransport.sg/" + path
    headers = {'AccountKey': ACCOUNT_KEY}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            return response.json()
    except httpx.RequestError as exc:
        print(f"An error occurred while requesting {exc.request.url!r}: {exc}")
        raise HTTPException(status_code=503, detail=f"Error contacting LTA API: {exc}")
    except Exception as e:
        print(f"An unexpected error occurred during API query: {e}")
        raise HTTPException(status_code=500, detail="Internal error during API query")

def timeDifferenceToNowSg(target_time_str: str, current_time_sg: datetime) -> int:
    """Calculates the difference in minutes between target time and provided current time."""
    if not target_time_str:
        return -100
    try:
        target_time = datetime.fromisoformat(target_time_str)

        time_diff = target_time - current_time_sg
        time_diff_minutes = int(time_diff.total_seconds() // 60)

        return max(0, time_diff_minutes) if time_diff_minutes >= -1 else 0
    except ValueError:
        print(f"Error parsing date string: {target_time_str}")
        return -100 # Indicate error or invalid time

async def process_bus_service(busService: Dict[str, Any], current_time_sg: datetime) -> Optional[Dict[str, Any]]:
    """Processes a single bus service with minimal overhead."""
    if not (service_no := busService.get("ServiceNo")):
        return None
    
    arrival_details = []
    for key in ('NextBus', 'NextBus2', 'NextBus3'):
        bus_data = busService.get(key)
        
        if bus_data and (estimated := bus_data.get('EstimatedArrival')):
            arrival_details.append({
                "busArrivalTime": timeDifferenceToNowSg(estimated, current_time_sg),
                "busLoad": bus_data.get("Load", "-"),
                "busFeature": bus_data.get("Feature", "-"),
                "busType": bus_data.get("Type", "-"),
                "busMonitored": bus_data.get("Monitored", 0),
                "busLongitude": bus_data.get("Longitude", "-"),
                "busLatitude": bus_data.get("Latitude", "-"),
            })
        else:
            arrival_details.append(DEFAULT_BUS.copy())
    
    return {
        "serviceNo": service_no,
        "serviceDetails": arrival_details
    }

DEFAULT_BUS = {
    "busArrivalTime": -100,
    "busLoad": "-",
    "busFeature": "-",
    "busType": "-",
    "busMonitored": 0,
    "busLongitude": "-",
    "busLatitude": "-",
}

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

async def getBusServicesFromLTA():
    results = []
    counter = 0
    flatten = lambda l: [y for x in l for y in x]
    print("Starting to fetch bus services data...")

    while True:
        print(f"Counter value: {counter}")
        result = await queryAPI("ltaodataservice/BusServices", {"$skip": str(counter)})
        results.append(result)
        counter += 500
        if counter >= 1000:
            break

    flattened_list = flatten([res["value"] for res in results if res.get("value")])

    return flattened_list

async def getCarParkAvailabilityFromLTA():
    results = []
    counter = 0
    flatten = lambda l: [y for x in l for y in x]
    print("Starting to fetch car park availability data...")

    while True:
        print(f"Counter value: {counter}")
        result = await queryAPI("ltaodataservice/CarParkAvailabilityv2", {"$skip": str(counter)})
        results.append(result)
        counter += 500
        if counter >= 4000:
            break

    flattened_list = flatten([res["value"] for res in results if res.get("value")])

    return flattened_list

async def getTrafficIncidentsFromLTA():
    results = []
    counter = 0
    flatten = lambda l: [y for x in l for y in x]
    print("Starting to fetch traffic incidents data...")

    while True:
        print(f"Counter value: {counter}")
        result = await queryAPI("ltaodataservice/TrafficIncidents", {"$skip": str(counter)})
        results.append(result)
        counter += 500
        if counter >= 1000:
            break

    flattened_list = flatten([res["value"] for res in results if res.get("value")])

    return flattened_list

async def getVMSFromLTA():
    results = []
    counter = 0
    flatten = lambda l: [y for x in l for y in x]
    print("Starting to fetch VMS data...")
    while True:
        print(f"Counter value: {counter}")
        result = await queryAPI("ltaodataservice/VMS", {"$skip": str(counter)})
        if not result.get("value"):  
            break
        results.append(result)
        counter += 500
    flattened_list = flatten([res["value"] for res in results if isinstance(res, dict) and res.get("value")])
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
            bus_stop_master_list[bus_stop].sort(key=service_sort_key)

        # Sort and format bus stops in service_dict
        for service_no in service_dict:
            for route in service_dict[service_no]["routes"]:
                route["busStopIDs"].sort(key=lambda x: x[0])  # Sort by StopSequence
                route["busStopIDs"] = [bus_stop_code for _, bus_stop_code in route["busStopIDs"]]
    
    bus_route_dict = list(service_dict.values())  # Convert service_dict to a list
    
    return bus_route_dict, dict(bus_stop_master_list)
        
def service_sort_key(service_no: str):
    if not service_no:
        return (float("inf"), "")

    match = re.match(r"(\d+)([A-Za-z]*)", service_no)
    if match:
        number = int(match.group(1))
        suffix = match.group(2)
        return (number, suffix)

    # Fallback: non-numeric service numbers go last
    return (float("inf"), service_no)

def natural_sort_key(service_no):
    match = re.match(r"(\d+)([A-Z]*)", service_no) 
    number_part = int(match.group(1))
    letter_part = match.group(2) or "" 
    return (number_part, letter_part)

def map_bus_services(bus_services: list) -> list:
    """Maps bus service data to camelCase."""
    camelcased_bus_services = []
    for service in bus_services:
        camelcased_service = {
            "serviceNo": service.get("ServiceNo"),
            "operator": service.get("Operator"),
            "direction": str(service.get("Direction")),
            "category": service.get("Category"),
            "originCode": service.get("OriginCode"),
            "destinationCode": service.get("DestinationCode"),
            "amPeakFreq": service.get("AM_Peak_Freq"),
            "amOffpeakFreq": service.get("AM_Offpeak_Freq"),
            "pmPeakFreq": service.get("PM_Peak_Freq"),
            "pmOffpeakFreq": service.get("PM_Offpeak_Freq"),
            "loopDesc": service.get("LoopDesc"),
        }
        camelcased_bus_services.append(camelcased_service)
    return camelcased_bus_services

def restructure_to_stops_only(raw_data: List[Dict]) -> Dict[str, Any]:
    """
    Restructure flat bus route data into stops-centric format only
    """
    stops = {}
    
    # Process each route entry
    for route in raw_data:
        service_no = route['ServiceNo']
        bus_stop_code = route['BusStopCode']
        direction = route['Direction']
        
        # Build stop structure
        if bus_stop_code not in stops:
            stops[bus_stop_code] = {
                "bus_stop_code": bus_stop_code,
                "services": {}
            }
        
        # Add service info to stop
        if service_no not in stops[bus_stop_code]["services"]:
            stops[bus_stop_code]["services"][service_no] = {
                "service_no": service_no,
                "operator": route['Operator'],
                "directions": {}
            }
        
        # Add direction info to service
        stops[bus_stop_code]["services"][service_no]["directions"][direction] = {
            "direction": direction,
            "stop_sequence": route['StopSequence'],
            "distance": route['Distance'],
            "schedules": {
                "weekday": {
                    "first_bus": route['WD_FirstBus'],
                    "last_bus": route['WD_LastBus']
                },
                "saturday": {
                    "first_bus": route['SAT_FirstBus'],
                    "last_bus": route['SAT_LastBus']
                },
                "sunday": {
                    "first_bus": route['SUN_FirstBus'],
                    "last_bus": route['SUN_LastBus']
                }
            }
        }
    
    return stops

def cache_headers(ttl_seconds: int = 86400):
    return {"Cache-Control": f"public, s-maxage={ttl_seconds}, stale-while-revalidate={ttl_seconds}"}

# def shapefile_to_station_json_clean(folder_path, shapefile_name, json_file):
#     """
#     Reads a shapefile of train station exits, converts coordinates to lat/lon,
#     removes 'MRT STATION'/'LRT STATION' from station names,
#     and outputs a JSON with station names and their exits.
#     """
#     # --- CHECK FOLDER AND FILE ---
#     if not os.path.exists(folder_path):
#         raise FileNotFoundError(f"Folder not found: {folder_path}")

#     shapefile_path = os.path.join(folder_path, shapefile_name)
#     if not os.path.exists(shapefile_path):
#         raise FileNotFoundError(f"Shapefile not found: {shapefile_path}")

#     print("Folder and shapefile found.")
#     print("Files in folder:", os.listdir(folder_path))

#     # --- READ SHAPEFILE ---
#     gdf = gpd.read_file(shapefile_path)

#     # --- BASIC INFO ---
#     print("\n--- Shapefile Info ---")
#     print("Columns:", gdf.columns)
#     print("CRS:", gdf.crs)
#     print("Number of features:", len(gdf))
#     print("First 5 rows:\n", gdf.head())

#     # --- CONVERT TO LAT/LON (WGS84) IF NEEDED ---
#     if gdf.crs != "EPSG:4326":
#         gdf = gdf.to_crs(epsg=4326)
#         print("\nConverted CRS to WGS84 (EPSG:4326).")

#     # --- BUILD JSON STRUCTURE ---
#     stations_dict = {}
#     for _, row in gdf.iterrows():
#         # Remove 'MRT STATION' or 'LRT STATION' from station name
#         name = re.sub(r'\s*(MRT|LRT) STATION', '', row["stn_name"], flags=re.IGNORECASE).strip()

#         exit_info = {
#             "exit_code": row["exit_code"],
#             "lon": row.geometry.x,
#             "lat": row.geometry.y
#         }
#         if name not in stations_dict:
#             stations_dict[name] = {"station": [exit_info]}
#         else:
#             stations_dict[name]["station"].append(exit_info)

#     # --- SAVE TO JSON ---
#     with open(json_file, "w", encoding="utf-8") as f:
#         json.dump(stations_dict, f, ensure_ascii=False, indent=4)

#     print(f"\nJSON saved to {json_file}")
#     return stations_dict

# # --- USAGE EXAMPLE ---
# folder_path = "TrainStationExit_Feb2025"
# shapefile_name = "Train_Station_Exit_Layer.shp"
# json_file = "stations.json"

# stations_json = shapefile_to_station_json_clean(folder_path, shapefile_name, json_file)