from datetime import datetime, timedelta, timezone
import time
from fastapi import APIRouter, HTTPException, Query
from routers.utils import queryAPI
from typing import List, Optional

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
