import json


json_path = 'bus_stop_master_list copy.json'
json_path2 = 'bus_stop_master_list.json'

def readJsonFile(file_path):
    try:
        extracted_list_bus_serviceno = []
        with open(file_path, 'r') as file:
            data = json.load(file)
            for r in data:
                extracted_list_bus_serviceno.append(r["serviceNo"])

            print(extracted_list_bus_serviceno)
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