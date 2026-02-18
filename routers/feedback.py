from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime

from routers.database import getDBClient

class FeedbackRequest(BaseModel):
    device_token: str
    message: str
    app_version: str

dbClient = getDBClient()

feedback_router = APIRouter()

@feedback_router.post("/submitFeedback")
async def submit_feedback(feedback: FeedbackRequest):
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
    except Exception as e:
        print(f"Error submitting feedback: {e}")
        raise HTTPException(status_code=500, detail="Error submitting feedback")