from pydantic import BaseModel
from datetime import datetime

class User(BaseModel):
    id: str | None = None
    email: str
    password: str | None = None
    passwordConfirm: str | None = None
    emailVisibility: bool
    verified: bool
    name: str 
    avatar: str | None = None
    created: datetime | None = None
    updated: datetime | None = None

class BusTimingRequest(BaseModel):
    busstopcode: str
    busservicenos: str
    userID: str

class GetUser(BaseModel):
    userID: str