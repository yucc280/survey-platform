"""MongoDB连接、启动索引及数据库依赖；配置读取backend/.env。"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from pymongo import ASCENDING, DESCENDING, MongoClient


def get_users(request: Request):
    return request.app.state.db.users

def get_surveys(request: Request):
    return request.app.state.db.surveys


def create_lifespan(test_database=None, test_secret: str | None = None):
    @asynccontextmanager
    async def lifespan(application: FastAPI):
        secret = test_secret if test_secret is not None else os.getenv("JWT_SECRET", "")
        if len(secret.encode("utf-8")) < 32:
            raise RuntimeError("请在 backend/.env 设置至少32字节的随机 JWT_SECRET")
        client = None
        try:
            if test_database is None:
                client = MongoClient(
                    os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017"),
                    serverSelectionTimeoutMS=3000, tz_aware=True,
                )
                client.admin.command("ping")
                database = client[os.getenv("MONGODB_DATABASE", "survey_pro1")]
            else:
                database = test_database
            # 唯一约束交给数据库，防止并发注册造成同名账号。
            database.users.create_index([("username", ASCENDING)], unique=True)
            database.surveys.create_index([("owner_id", ASCENDING), ("created_at", DESCENDING)])
            database.questions.create_index([("owner_id", ASCENDING), ("created_at", DESCENDING)])
            database.question_banks.create_index("question_ids")
            database.question_banks.create_index([("owner_id", ASCENDING), ("created_at", DESCENDING)])
            database.surveys.create_index("questions.source.question_id")
            database.responses.create_index(
                [("survey_id", ASCENDING), ("user_id", ASCENDING)], unique=True,
                partialFilterExpression={"single_submission": True}, name="one_submission_per_user",
            )
            database.responses.create_index([
                ("survey_id", ASCENDING), ("user_id", ASCENDING),
                ("submitted_at", DESCENDING), ("_id", DESCENDING),
            ])
            application.state.db = database
            application.state.jwt_secret = secret
            yield
        finally:
            if client is not None:
                client.close()

    return lifespan
