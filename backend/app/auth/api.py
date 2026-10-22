"""账号注册、登录和个人信息接口及简单请求模型。"""
import re
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictStr, field_validator
from pymongo.errors import DuplicateKeyError

from app.database import get_users
from .dependencies import current_user
from .security import DUMMY_HASH, TOKEN_SECONDS, create_token, hasher, verify_password


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: StrictStr
    password: StrictStr

    @field_validator("username")
    @classmethod
    def valid_username(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[A-Za-z0-9_]{3,30}", value):
            raise ValueError("用户名须为3～30位英文字母、数字或下划线")
        return value

    @field_validator("password")
    @classmethod
    def valid_password(cls, value: str) -> str:
        if not 6 <= len(value) <= 30:
            raise ValueError("密码须为6～30个字符")
        return value

class UserOut(BaseModel):
    id: str
    username: str
    created_at: datetime

class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = TOKEN_SECONDS

def public_user(user: dict) -> UserOut:
    return UserOut(id=str(user["_id"]), username=user["username"], created_at=user["created_at"])


router = APIRouter()


@router.post("/api/auth/register", response_model=UserOut, status_code=201)
def register(body: Credentials, users=Depends(get_users)):
    user = {
        "_id": ObjectId(), "username": body.username,
        "password_hash": hasher.hash(body.password),
        "created_at": datetime.now(timezone.utc),
    }
    try:
        users.insert_one(user)
    except DuplicateKeyError:
        raise HTTPException(409, "用户名已存在")
    return public_user(user)

@router.post("/api/auth/login", response_model=TokenOut)
def login(body: Credentials, request: Request, users=Depends(get_users)):
    user = users.find_one({"username": body.username})
    valid = verify_password(body.password, user["password_hash"] if user else DUMMY_HASH)
    if not valid or user is None:
        raise HTTPException(401, "用户名或密码错误", headers={"WWW-Authenticate": "Bearer"})
    return TokenOut(access_token=create_token(str(user["_id"]), request.app.state.jwt_secret))

@router.get("/api/auth/me", response_model=UserOut)
def me(user=Depends(current_user)):
    return public_user(user)
