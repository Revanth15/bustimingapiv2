import time
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from datetime import datetime

from routers.database import getDBClient
from routers.utils import emit_route_exception, emit_route_http_error, redact_device_token, redact_feedback_message

class FeedbackRequest(BaseModel):
    device_token: str
    message: str
    app_version: str

dbClient = getDBClient()

feedback_router = APIRouter()

@feedback_router.post("/submitFeedback")
async def submit_feedback(request: Request, feedback: FeedbackRequest):
    t0 = time.perf_counter()
    stage = "insert_feedback"
    try:
        data = {
            "device_token": feedback.device_token,
            "message": feedback.message,
            "app_version": feedback.app_version,
            "created_at": datetime.utcnow().isoformat()
        }
        response = dbClient.table("feedback").insert(data).execute()
        if response.data:
            return {"message": "Feedback submitted successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to insert feedback")
    except HTTPException as exc:
        emit_route_http_error(
            "/submitFeedback",
            request,
            exc,
            t0,
            stage=stage,
            **redact_device_token(feedback.device_token),
            **redact_feedback_message(feedback.message),
            app_version=feedback.app_version,
        )
        raise
    except Exception as exc:
        print(f"Error submitting feedback: {exc}")
        emit_route_exception(
            "/submitFeedback",
            request,
            exc,
            t0,
            stage=stage,
            **redact_device_token(feedback.device_token),
            **redact_feedback_message(feedback.message),
            app_version=feedback.app_version,
        )
        raise HTTPException(status_code=500, detail="Error submitting feedback")
