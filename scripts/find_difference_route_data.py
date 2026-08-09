import json


json_path = 'bus_data_latest.json'
json_path2 = 'bus_data_outdated.json'

def readJsonFile(file_path):
    try:
        extracted_list_bus_serviceno = []
        with open(file_path, 'r') as file:
            data = json.load(file)
            for r in data:
                extracted_list_bus_serviceno.append(r["serviceNo"])

            # print(extracted_list_bus_serviceno)
            print(len(extracted_list_bus_serviceno))
            return extracted_list_bus_serviceno
    except FileNotFoundError:
        print(f"Error: The file '{file_path}' was not found.")
    except json.JSONDecodeError:
        print("Error: Failed to decode JSON from the file.")

# Compare the number of bus services available vs the number of services saved

latestBuses = readJsonFile(json_path)
outdatedBuses = readJsonFile(json_path2)
c = list(set(latestBuses) - set(outdatedBuses))
print(c)
d = list(set(outdatedBuses) - set(latestBuses))
print(d)

# ============================================================
# Bus Service Comparison Script – Data Preparation Guide
# ============================================================

# PURPOSE:
# This script compares two datasets of bus services to identify:
# - New services (present in latest but not outdated)
# - Removed services (present in outdated but not latest)


# ------------------------------------------------------------
# REQUIRED JSON FILES
# ------------------------------------------------------------

# 1. bus_data_latest.json
# Source: /extractBusRoutesData API
# IMPORTANT: Use ONLY the "message" field (which contains the list)

# Steps:
# 1. Call /extractBusRoutesData
# 2. Extract the "message" field from the response
# 3. Save that list directly into bus_data_latest.json

# -----------------------------------------------------------

# 2. bus_data_outdated.json
# Source: /getBusRoutesData API

# Steps:
# 1. Call /getBusRoutesData
# 2. Save the full response directly into bus_data_outdated.json

# ------------------------------------------------------------
# EXECUTION WORKFLOW
# ------------------------------------------------------------

# 1. Update bus_data_latest.json using /extractBusRoutesData
# 2. Update bus_data_outdated.json using /getBusRoutesData
# 3. Run this script

# cd scripts
# python3 find_difference_route_data.py 


# ------------------------------------------------------------
# OUTPUT INTERPRETATION
# ------------------------------------------------------------

# c = services present in latest but NOT in outdated (NEW services)
# d = services present in outdated but NOT in latest (REMOVED services)