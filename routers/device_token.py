from datetime import datetime
import time
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import pytz
from routers.database import getDBClient
from routers.utils import emit_route_exception, emit_route_http_error, redact_device_token

device_token_router = APIRouter()

supabase = getDBClient()

class DeviceToken(BaseModel):
    token: str
    device_type: str
    device_model: str
    system_version: str
    app_version: str
    push_to_start_token: str | None = None

@device_token_router.post("/registerDeviceToken")
async def register_device_token(request: Request, device: DeviceToken):
    """
    Store an iOS device token in the Supabase devices table.
    - Accepts a device token in the request body.
    - Stores token as id, sets registered_date (SGT timestamp).
    - Preserves created_at for existing tokens, updates registered_date on conflict.
    """
    t0 = time.perf_counter()
    stage = "upsert_device_token"
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

        if device.push_to_start_token:
            device_data["push_to_start_token"] = device.push_to_start_token

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

    except HTTPException as exc:
        emit_route_http_error(
            "/registerDeviceToken",
            request,
            exc,
            t0,
            stage=stage,
            **redact_device_token(device.token),
            device_type=device.device_type,
            device_model=device.device_model,
            system_version=device.system_version,
            app_version=device.app_version,
            has_push_to_start_token=bool(device.push_to_start_token),
        )
        raise
    except Exception as exc:
        print(f"Error storing device token: {exc}")
        emit_route_exception(
            "/registerDeviceToken",
            request,
            exc,
            t0,
            stage=stage,
            **redact_device_token(device.token),
            device_type=device.device_type,
            device_model=device.device_model,
            system_version=device.system_version,
            app_version=device.app_version,
            has_push_to_start_token=bool(device.push_to_start_token),
        )
        raise HTTPException(status_code=500, detail=f"Error: {str(exc)}")

@device_token_router.post("/deleteDeviceToken")
async def delete_device_token(request: Request, device: DeviceToken):
    """
    Deletes an iOS device token in the Supabase devices table.
    - Accepts a device token in the request body.
    """
    t0 = time.perf_counter()
    stage = "delete_device_token"
    try:
        response = (supabase.table("devices")
                    .delete()
                    .eq("id",device.token)
                    .execute())

        print(f"Deleted device token: {device.token}")

        return JSONResponse(content={"message": "Device token deleted successfully"})

    except HTTPException as exc:
        emit_route_http_error(
            "/deleteDeviceToken",
            request,
            exc,
            t0,
            stage=stage,
            **redact_device_token(device.token),
            device_type=device.device_type,
            device_model=device.device_model,
            system_version=device.system_version,
            app_version=device.app_version,
            has_push_to_start_token=bool(device.push_to_start_token),
        )
        raise
    except Exception as exc:
        print(f"Error deleting device token: {exc}")
        emit_route_exception(
            "/deleteDeviceToken",
            request,
            exc,
            t0,
            stage=stage,
            **redact_device_token(device.token),
            device_type=device.device_type,
            device_model=device.device_model,
            system_version=device.system_version,
            app_version=device.app_version,
            has_push_to_start_token=bool(device.push_to_start_token),
        )
        raise HTTPException(status_code=500, detail=f"Error: {str(exc)}")
