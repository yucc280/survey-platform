"""密码验证与登录令牌；不把数据库访问混入这些函数。"""
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

hasher = PasswordHasher()
# 用户不存在时也执行一次密码验证，减少登录失败的耗时差异。
DUMMY_HASH = hasher.hash("not-a-real-user-password")
TOKEN_SECONDS = 2 * 60 * 60


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return hasher.verify(password_hash, password)
    except VerificationError:
        return False


def create_token(user_id: str, secret: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": user_id, "iat": now, "exp": now + timedelta(seconds=TOKEN_SECONDS)},
        secret, algorithm="HS256",
    )
