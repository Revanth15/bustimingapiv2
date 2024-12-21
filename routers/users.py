from fastapi import APIRouter, HTTPException, Query
from routers.database import create_dbuser, get_dbuser, getDBClient
from routers.schemas import BusTimingRequest, GetUser, User
from routers.utils import getBusArrivalDetails, queryAPI

dbClient = getDBClient()

users_router = APIRouter()

@users_router.post("/user")
async def create_user(user_data: User):
    try:
        # User.validate_passwords(user_data.password, user_data.passwordConfirm)

        user_dict = user_data.dict()
        user = create_dbuser(user_dict)
        return user
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# FastAPI route to fetch a user by ID
@users_router.get("/user")
async def get_user(userID: GetUser):
    try:
        user = get_dbuser(userID.userID)
        return user
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
    