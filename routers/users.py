import time
from fastapi import APIRouter, HTTPException, Request
from routers.database import create_dbuser, get_dbuser, getDBClient
from routers.schemas import GetUser, User
from routers.utils import emit_route_exception, emit_route_http_error, redact_email

dbClient = getDBClient()

users_router = APIRouter()

@users_router.post("/user")
async def create_user(request: Request, user_data: User):
    t0 = time.perf_counter()
    stage = "create_user"
    try:
        # User.validate_passwords(user_data.password, user_data.passwordConfirm)

        user_dict = user_data.dict()
        user = create_dbuser(user_dict)
        return user
    except ValueError as ve:
        emit_route_http_error(
            "/user",
            request,
            HTTPException(status_code=400, detail=str(ve)),
            t0,
            stage=stage,
            **redact_email(user_data.email),
            name_present=bool(user_data.name),
        )
        raise HTTPException(status_code=400, detail=str(ve))
    except HTTPException as he:
        emit_route_http_error(
            "/user",
            request,
            he,
            t0,
            stage=stage,
            **redact_email(user_data.email),
            name_present=bool(user_data.name),
        )
        raise he
    except Exception as exc:
        print(f"Unexpected error: {exc}")
        emit_route_exception(
            "/user",
            request,
            exc,
            t0,
            stage=stage,
            **redact_email(user_data.email),
            name_present=bool(user_data.name),
        )
        raise HTTPException(status_code=500, detail="Internal server error")


# FastAPI route to fetch a user by ID
@users_router.get("/user")
async def get_user(request: Request, userID: GetUser):
    t0 = time.perf_counter()
    stage = "get_user"
    try:
        user = get_dbuser(userID.userID)
        return user
    except HTTPException as he:
        emit_route_http_error("/user", request, he, t0, stage=stage, user_id=userID.userID)
        raise he
    except Exception as exc:
        print(f"Unexpected error: {exc}")
        emit_route_exception("/user", request, exc, t0, stage=stage, user_id=userID.userID)
        raise HTTPException(status_code=500, detail="Internal server error")
    
