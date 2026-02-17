from datetime import datetime
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import pytz
from routers.database import getDBClient

device_token_router = APIRouter()

supabase = getDBClient()

class DeviceToken(BaseModel):
    token: str
    device_type: str
    device_model: str
    system_version: str
    app_version: str

@device_token_router.post("/registerDeviceToken")
async def register_device_token(device: DeviceToken):
    """
    Store an iOS device token in the Supabase devices table.
    - Accepts a device token in the request body.
    - Stores token as id, sets registered_date (SGT timestamp).
    - Preserves created_at for existing tokens, updates registered_date on conflict.
    """
    try:
        sgt_timezone = pytz.timezone("Asia/Singapore")
        current_timestamp = datetime.now(sgt_timezone).isoformat()

        device_data = {
            "id": device.token,
            "device_type": device.device_type,
            "device_model": device.device_model,
            "system_version": device.system_version,
            "app_version": device.app_version,
            "registered_date": current_timestamp
        }

        # Upsert into devices table
        response = supabase.table("devices").upsert(
            [device_data],
            on_conflict="id",
            ignore_duplicates=False, 
            returning="minimal" 
        ).execute()

        # Check if the operation was successful
        # if not response.data:
        #     existing = supabase.table("devices").select("id").eq("id", device.token).execute()
        #     if existing.data:
        #         print(f"Token {device.token} updated successfully")
        #     else:
        #         raise HTTPException(status_code=500, detail="Failed to store device token")

        print(f"Stored/Updated device token: {device.token}")

        return JSONResponse(content={"message": "Device token registered successfully"})

    except Exception as e:
        print(f"Error storing device token: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@device_token_router.post("/deleteDeviceToken")
async def delete_device_token(device: DeviceToken):
    """
    Deletes an iOS device token in the Supabase devices table.
    - Accepts a device token in the request body.
    """
    try:
        response = (supabase.table("devices")
                    .delete()
                    .eq("id",device.token)
                    .execute())

        print(f"Deleted device token: {device.token}")

        return JSONResponse(content={"message": "Device token deleted successfully"})

    except Exception as e:
        print(f"Error deleting device token: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")