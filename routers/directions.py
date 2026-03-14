import json
import os
from fastapi import APIRouter, HTTPException, Query
import httpx
from pydantic import BaseModel
from datetime import datetime
import polyline

from routers.utils import getEnvVariable

directions_router = APIRouter()

ONEMAP_EMAIL = getEnvVariable("ONEMAP_EMAIL")
ONEMAP_PASSWORD = getEnvVariable("ONEMAP_PASSWORD")
ONEMAP_API_TOKEN = getEnvVariable("ONEMAP_API_TOKEN")
ONEMAP_AUTH_URL = "https://www.onemap.gov.sg/api/auth/post/getToken"
ONEMAP_ROUTE_URL = "https://www.onemap.gov.sg/api/public/routingsvc/route"
TOKEN_CACHE_FILE = "onemap_token_cache.json"

_cached_token = None
_token_expiry = 0

def load_token_from_file():
    """Loads the token from our JSON file if it exists."""
    global _cached_token, _token_expiry
    if os.path.exists(TOKEN_CACHE_FILE):
        try:
            with open(TOKEN_CACHE_FILE, "r") as f:
                data = json.load(f)
                _cached_token = data.get("access_token")
                _token_expiry = data.get("expiry_timestamp", 0)
        except json.JSONDecodeError:
            pass # File is empty or corrupted, we'll just fetch a new one

def save_token_to_file(token, expiry):
    """Saves the fresh token to our JSON file."""
    with open(TOKEN_CACHE_FILE, "w") as f:
        json.dump({
            "access_token": token,
            "expiry_timestamp": expiry
        }, f)

# Load the token from the file when the script first starts
load_token_from_file()

async def get_onemap_token():
    """
    Returns a valid OneMap token. Fetches a new one only if the 
    cached token is missing or expired.
    """
    global _cached_token, _token_expiry
    
    current_time = datetime.now().timestamp()
    
    if _cached_token and current_time < (_token_expiry - 60):
        return _cached_token
        
    payload = {"email": ONEMAP_EMAIL, "password": ONEMAP_PASSWORD}
    
    async with httpx.AsyncClient() as client:
        response = await client.post(ONEMAP_AUTH_URL, json=payload)
        
    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Failed to authenticate")
    
    data = response.json()
    
    _cached_token = data.get("access_token")
    _token_expiry = int(data.get("expiry_timestamp", 0))
    
    save_token_to_file(_cached_token, _token_expiry)
    
    return _cached_token

class TransitRouteRequest(BaseModel):
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    date: str = None
    time: str = None

@directions_router.post("/transit_route_full")
async def get_transit_route_full(body: TransitRouteRequest):
    """
    Calls OneMap public transport routing API with start/end points.
    """

    headers = {
        "Authorization": f"{ONEMAP_API_TOKEN}"
    }

    start = f"{body.start_lat},{body.start_lon}"
    end = f"{body.end_lat},{body.end_lon}"

    params = {
        "start": start,
        "end": end,
        "routeType": "pt",  
        "mode": "transit",
        "n_itineraries": "3"
    }

    if body.date:
        params["date"] = body.date
    if body.time:
        params["time"] = body.time

    async with httpx.AsyncClient() as client:
        response = await client.get(ONEMAP_ROUTE_URL, headers=headers, params=params)

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"OneMap API error: {response.text}"
        )

    return response.json()

@directions_router.post("/transit_route")
async def get_transit_route(body: TransitRouteRequest):
    """
    Calls OneMap public transport routing API and decodes all leg geometries
    """

    token = await get_onemap_token()

    headers = {
        "Authorization": token
    }

    start = f"{body.start_lat},{body.start_lon}"
    end = f"{body.end_lat},{body.end_lon}"

    params = {
        "start": start,
        "end": end,
        "routeType": "pt",
        "mode": "transit", 
        "n_itineraries": "3"
    }

    if body.date:
        params["date"] = body.date
    if body.time:
        params["time"] = body.time

    async with httpx.AsyncClient() as client:
        response = await client.get(ONEMAP_ROUTE_URL, headers=headers, params=params)

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"OneMap API error: {response.text}"
        )

    data = response.json()

    # ------------------------------------------
    # Loop through itineraries and legs
    # Decode all legGeometry points
    # ------------------------------------------
    decoded_itineraries = []

    for itin_index, itinerary in enumerate(data.get("plan", {}).get("itineraries", [])):
        decoded_legs = []

        for leg_index, leg in enumerate(itinerary.get("legs", [])):
            encoded_poly = leg.get("legGeometry", {}).get("points")
            if encoded_poly:
                coords = polyline.decode(encoded_poly)  # List of (lat, lon)
            else:
                coords = []

            intermediate_stops = []
            if leg.get("transitLeg"):
                for stop in leg.get("intermediateStops", []):
                    intermediate_stops.append({
                        "name": stop.get("name"),
                        "arrival": stop.get("arrival"),
                        "departure": stop.get("departure"),
                        "lat": stop.get("lat"),
                        "lon": stop.get("lon"),
                        "stopCode": stop.get("stopCode")
                    })

            decoded_legs.append({
                "mode": leg.get("mode"),
                "distance": leg.get("distance"),
                "start_name": leg.get("from", {}).get("name"),
                "start_code": leg.get("from", {}).get("stopCode"),
                "end_name": leg.get("to", {}).get("name"),
                "end_code": leg.get("to", {}).get("stopCode"),
                "route_id": leg.get("routeId"),
                "coordinates": coords,
                "duration": leg.get("duration"),
                "intermediate_stops": intermediate_stops
            })

        decoded_itineraries.append({
            "duration": itinerary.get("duration"),
            "transfers": itinerary.get("transfers"),
            "fare": itinerary.get("fare"),
            "walk_distance": itinerary.get("walkDistance"),
            "start_time": itinerary.get("startTime"),
            "end_time": itinerary.get("endTime"),
            "legs": decoded_legs
        })

    return {
        "from": data.get("plan", {}).get("from"),
        "to": data.get("plan", {}).get("to"),
        "itineraries": decoded_itineraries
    }