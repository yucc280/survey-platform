"""从Bearer令牌识别当前用户，供各业务模块复用。"""
from typing import Annotated

import jwt
from bson import ObjectId
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.database import get_users

bearer = HTTPBearer(auto_error=False)


def unauthorized() -> HTTPException:
    return HTTPException(401, "请登录，或重新登录后重试", headers={"WWW-Authenticate": "Bearer"})

def current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    users=Depends(get_users),
) -> dict:
    if credentials is None:
        raise unauthorized()
    try:
        claims = jwt.decode(
            credentials.credentials, request.app.state.jwt_secret,
            algorithms=["HS256"], options={"require": ["sub", "exp", "iat"]},
        )
        user_id = claims["sub"]
        if not isinstance(user_id, str) or not ObjectId.is_valid(user_id):
            raise unauthorized()
    except jwt.InvalidTokenError:
        raise unauthorized()
    user = users.find_one({"_id": ObjectId(user_id)}, {"password_hash": 0})
    if user is None:
        raise unauthorized()
    return user
