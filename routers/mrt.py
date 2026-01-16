from datetime import datetime, timedelta, timezone
import json
import time
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from routers.database import getDBClient
from routers.utils import cache_headers, queryAPI
from typing import List, Optional

dbClient = getDBClient()
MRT_router = APIRouter()

@MRT_router.get("/mrt_crowd_density")
async def get_mrt_crowd_density(mrt_lines: List[str] = Query(..., description="List of MRT lines")):
    try:
        start_time = time.perf_counter()
        all_results = {}

        for mrt_line in mrt_lines:
            ltaResponse = await queryAPI("ltaodataservice/PCDRealTime", {"TrainLine": mrt_line})
            mrtCrowdDensityRes = ltaResponse.get("value", [])

            if not mrtCrowdDensityRes:
                all_results[mrt_line] = {
                    "StartTime": "",
                    "EndTime": "",
                    "Stations": []
                }
                continue

            # Extract StartTime and EndTime once (from first item)
            first_entry = mrtCrowdDensityRes[0]
            res = {
                "StartTime": first_entry.get("StartTime", ""),
                "EndTime": first_entry.get("EndTime", ""),
                "Stations": []
            }

            # Build station list without Start/EndTime
            res["Stations"] = [
                {
                    "Station": station.get("Station", ""),
                    "CrowdLevel": station.get("CrowdLevel", "")
                }
                for station in mrtCrowdDensityRes
            ]

            all_results[mrt_line] = res

        end_time = time.perf_counter()
        loop_duration = end_time - start_time
        print(f"Processing took {loop_duration:.6f} seconds")

        return {
            "lines": all_results,
            "processing_time_seconds": loop_duration
        }

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@MRT_router.get("/getMRTStationCoords")
async def get_stationCoord_data():
    key = "stationCoords"
    try:
        response = dbClient.table("jsons").select("json_value").eq("id", key).execute()
        if response.data:
            return response.data[0]["json_value"]
        else:
            return {"message": "No records available"}
    except Exception as e:
        print(f"Error fetching mrt Station Coordinates data: {e}")
        raise HTTPException(status_code=500, detail="Error fetching mrt Station Coordinates data")