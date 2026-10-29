"""账号 API 测试：内存替身隔离数据库，MongoDB 索引并发语义需后续集成验证。"""
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

from app.main import create_app
from app.auth.security import hasher


class UsersStub:
    def __init__(self):
        self.rows = []

    def create_index(self, keys, unique=False, **kwargs):
        pass

    def insert_one(self, doc):
        if "username" in doc and any(row.get("username") == doc["username"] for row in self.rows):
            raise DuplicateKeyError("duplicate username")
        if doc.get("single_submission") and any(
            row.get("single_submission") and row.get("survey_id") == doc["survey_id"] and row.get("user_id") == doc["user_id"]
            for row in self.rows
        ):
            raise DuplicateKeyError("duplicate response")
        self.rows.append(deepcopy(doc))

    def find_one(self, query, projection=None):
        for row in self.rows:
            if all(row.get(key) == value for key, value in query.items()):
                result = deepcopy(row)
                if projection:
                    for key, include in projection.items():
                        if not include:
                            result.pop(key, None)
                return result
        return None

    def find(self, query, projection=None):
        rows = []
        for row in self.rows:
            if all(row.get(key) in value["$in"] if isinstance(value, dict) and "$in" in value
                   else row.get(key) == value for key, value in query.items()):
                if projection and any(projection.values()):
                    rows.append({key: deepcopy(value) for key, value in row.items()
                                 if key == "_id" or projection.get(key)})
                else:
                    rows.append(deepcopy(row))
        return rows


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.users = UsersStub()
        self.secret = "test-only-secret-" * 4
        self.client = TestClient(create_app(SimpleNamespace(users=self.users, surveys=UsersStub(), responses=UsersStub(), questions=UsersStub(), question_banks=UsersStub()), self.secret))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def register(self, username="Alice", password="123456"):
        return self.client.post("/api/auth/register", json={"username": username, "password": password})

    def test_register_login_me_and_hash(self):
        result = self.register(" Alice ")
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.json()["username"], "Alice")
        self.assertNotIn("password_hash", result.json())
        stored = self.users.rows[0]
        self.assertNotIn("password", stored)
        self.assertTrue(stored["password_hash"].startswith("$argon2id$"))
        self.assertTrue(hasher.verify(stored["password_hash"], "123456"))
        token = self.client.post("/api/auth/login", json={"username": "Alice", "password": "123456"}).json()["access_token"]
        profile = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.json()["id"], result.json()["id"])
        self.assertNotIn("password_hash", profile.json())

    def test_unique_and_case_sensitive_names(self):
        self.assertEqual(self.register().status_code, 201)
        self.assertEqual(self.register(" Alice ").status_code, 409)
        self.assertEqual(self.register("alice").status_code, 201)

    def test_password_boundaries_and_preserve_spaces(self):
        for size, expected in [(5, 422), (6, 201), (30, 201), (31, 422)]:
            self.assertEqual(self.register(f"user{size}", "x" * size).status_code, expected)
        self.register("spaces", " secret ")
        result = self.client.post("/api/auth/login", json={"username": "spaces", "password": "secret"})
        self.assertEqual(result.status_code, 401)

    def test_invalid_username_and_wrong_credentials(self):
        self.assertEqual(self.register("中文").status_code, 422)
        self.assertEqual(self.register("ab").status_code, 422)
        self.register()
        for username in ["Alice", "missing"]:
            result = self.client.post("/api/auth/login", json={"username": username, "password": "incorrect"})
            self.assertEqual(result.status_code, 401)
            self.assertEqual(result.json()["detail"], "用户名或密码错误")

    def test_missing_invalid_expired_and_unknown_user_tokens(self):
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)
        now = datetime.now(timezone.utc)
        for token in [
            "invalid",
            jwt.encode({"sub": "0" * 24, "iat": now, "exp": now - timedelta(seconds=1)}, self.secret, algorithm="HS256"),
            jwt.encode({"sub": "0" * 24, "iat": now, "exp": now + timedelta(hours=1)}, self.secret, algorithm="HS256"),
            jwt.encode({"sub": "0" * 24, "iat": now, "exp": now + timedelta(hours=1)}, "wrong-secret-" * 4, algorithm="HS256"),
        ]:
            self.assertEqual(self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code, 401)


if __name__ == "__main__":
    unittest.main()
