"""问卷草稿接口测试；可选真实 MongoDB 用唯一临时数据库隔离数据。"""
import os
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from bson import ObjectId
from fastapi.testclient import TestClient
from pymongo import MongoClient

from app.main import create_app
from app.surveys.jumps import first_jump_target
from app.auth.security import create_token
from tests.test_auth import UsersStub


class CursorStub:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, keys):
        for key, direction in reversed(keys):
            self.rows.sort(key=lambda row: row[key], reverse=direction < 0)
        return self

    def skip(self, amount):
        self.rows = self.rows[amount:]
        return self

    def limit(self, amount):
        self.rows = self.rows[:amount]
        return self

    def __iter__(self):
        return iter(self.rows)


class SurveysStub(UsersStub):
    def aggregate(self, pipeline):
        # 仅支持统计测试所需的 match/sort/group；真实库测试验证MongoDB管道本身。
        if [next(iter(stage)) for stage in pipeline] != ["$match", "$sort", "$group"]:
            raise NotImplementedError("unsupported test aggregation")
        rows = list(self.find(pipeline[0]["$match"]).sort(list(pipeline[1]["$sort"].items())))
        grouped = {}
        for row in rows:
            entry = grouped.setdefault(row["user_id"], {"_id": row["user_id"], "latest": row, "submission_count": 0})
            entry["submission_count"] += 1
        return list(grouped.values())

    def find_one_and_update(self, query, update, return_document=None):
        for row in self.rows:
            matches = all(row.get(key) == value for key, value in query.items() if key != "$expr")
            if "$expr" in query:
                deadline = row.get("deadline")
                matches = matches and (deadline is None or deadline > datetime.now(timezone.utc))
            if matches:
                row.update(deepcopy(update["$set"]))
                return deepcopy(row)
        return None

    def delete_one(self, query):
        for index, row in enumerate(self.rows):
            if all(row.get(key) == value for key, value in query.items()):
                self.rows.pop(index)
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    def update_one(self, query, update):
        self.find_one_and_update(query, update)

    def find(self, query, projection=None):
        rows = [deepcopy(row) for row in self.rows
                if all(row.get(key) == value for key, value in query.items())]
        if projection:
            for row in rows:
                for key, include in projection.items():
                    if not include:
                        row.pop(key, None)
        return CursorStub(rows)

    def count_documents(self, query):
        return sum(all(row.get(key) == value for key, value in query.items()) for row in self.rows)


class SurveyTests(unittest.TestCase):
    use_mongo = False

    def setUp(self):
        self.secret = "test-survey-secret-" * 4
        if self.use_mongo:
            mongo = MongoClient(os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017"),
                                serverSelectionTimeoutMS=3000, tz_aware=True)
            self.addCleanup(mongo.close)
            mongo.admin.command("ping")
            # 固定测试前缀 + 随机ID，不访问或清空现有业务数据库。
            database_name = "survey_pro1_test_" + uuid.uuid4().hex
            self.database = mongo[database_name]
            self.addCleanup(mongo.drop_database, database_name)
        else:
            self.database = SimpleNamespace(users=UsersStub(), surveys=SurveysStub(), responses=SurveysStub())
        self.alice = ObjectId()
        self.bob = ObjectId()
        for user_id, name in [(self.alice, "Alice"), (self.bob, "Bob")]:
            self.database.users.insert_one({"_id": user_id, "username": name})
        self.client = TestClient(create_app(self.database, self.secret))
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.headers = {"Authorization": "Bearer " + create_token(str(self.alice), self.secret)}
        self.bob_headers = {"Authorization": "Bearer " + create_token(str(self.bob), self.secret)}

    def create(self, body=None, headers=None):
        return self.client.post("/api/surveys", json=body or {"title": "课程问卷"},
                                headers=headers if headers is not None else self.headers)

    def test_delete_draft_and_list(self):
        draft = self.create().json()
        other = self.create(headers=self.bob_headers).json()
        url = f"/api/surveys/{draft['id']}"
        result = self.client.delete(url, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["message"], "问卷草稿已删除")
        self.assertIsNone(self.database.surveys.find_one({"_id": ObjectId(draft["id"])}))
        self.assertEqual(self.client.get(url, headers=self.headers).status_code, 404)
        self.assertEqual(self.client.delete(url, headers=self.headers).status_code, 404)
        self.assertEqual(self.client.get("/api/surveys", headers=self.headers).json()["total"], 0)
        self.assertIsNotNone(self.database.surveys.find_one({"_id": ObjectId(other["id"])}))

    def test_delete_permission_and_invalid_ids(self):
        draft = self.create().json()
        url = f"/api/surveys/{draft['id']}"
        self.assertEqual(self.client.delete(url).status_code, 401)
        self.assertEqual(self.client.delete(url, headers=self.bob_headers).status_code, 404)
        for survey_id in ["invalid", str(ObjectId())]:
            self.assertEqual(self.client.delete(f"/api/surveys/{survey_id}", headers=self.headers).status_code, 404)
        self.assertIsNotNone(self.database.surveys.find_one({"_id": ObjectId(draft["id"])}))

    def test_delete_non_draft_preserves_survey_and_responses(self):
        for status, deadline in [("published", None), ("published", datetime.now(timezone.utc) - timedelta(days=1)), ("closed", None)]:
            with self.subTest(status=status, deadline=deadline):
                draft = self.create().json()
                survey_id = ObjectId(draft["id"])
                self.database.surveys.update_one({"_id": survey_id}, {"$set": {"status": status, "deadline": deadline}})
                response_id = ObjectId()
                self.database.responses.insert_one({"_id": response_id, "survey_id": survey_id})
                before = self.database.surveys.find_one({"_id": survey_id})
                result = self.client.delete(f"/api/surveys/{survey_id}", headers=self.headers)
                self.assertEqual(result.status_code, 409)
                self.assertEqual(result.json()["detail"], "当前尚不支持该状态下的问卷删除")
                self.assertEqual(self.database.surveys.find_one({"_id": survey_id}), before)
                self.assertIsNotNone(self.database.responses.find_one({"_id": response_id}))

    def test_delete_rechecks_concurrent_publish_and_edit(self):
        for changes in [{"status": "published"}, {"title": "另一窗口已修改"}]:
            with self.subTest(changes=changes):
                draft = self.create().json()
                survey_id = ObjectId(draft["id"])
                previous = self.database.surveys.find_one({"_id": survey_id})
                def read_then_change(*args):
                    self.database.surveys.update_one({"_id": survey_id}, {"$set": changes})
                    return previous
                with patch("app.surveys.api.owned_survey", side_effect=read_then_change):
                    result = self.client.delete(f"/api/surveys/{survey_id}", headers=self.headers)
                self.assertEqual(result.status_code, 409)
                stored = self.database.surveys.find_one({"_id": survey_id})
                self.assertIsNotNone(stored)
                for key, value in changes.items():
                    self.assertEqual(stored[key], value)

    def test_draft_defaults_and_persistence(self):
        result = self.create({"title": "课程问卷", "description": "用于课程实验"})
        self.assertEqual(result.status_code, 201)
        body = result.json()
        self.assertEqual(body["status"], "draft")
        self.assertEqual(body["questions"], [])
        self.assertIsNone(body["deadline"])
        self.assertFalse(body["allow_anonymous"])
        self.assertFalse(body["allow_repeat"])
        self.assertEqual(body["owner_id"], str(self.alice))
        self.assertEqual(body["created_at"], body["updated_at"])
        stored = self.database.surveys.find_one({"_id": ObjectId(body["id"])})
        self.assertEqual(stored["owner_id"], self.alice)
        self.assertIsInstance(stored["_id"], ObjectId)
        detail = self.client.get("/api/surveys/" + body["id"], headers=self.headers)
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["title"], "课程问卷")

    def test_owner_isolation_and_missing_ids(self):
        created = self.create().json()
        self.create(headers=self.bob_headers)
        listing = self.client.get("/api/surveys", headers=self.headers).json()
        self.assertEqual(listing["total"], 1)
        self.assertEqual(listing["items"][0]["id"], created["id"])
        self.assertNotIn("questions", listing["items"][0])
        for identifier in [created["id"], str(ObjectId()), "bad-id"]:
            denied = self.client.get("/api/surveys/" + identifier, headers=self.bob_headers)
            self.assertEqual(denied.status_code, 404)

    def test_pagination_and_newest_first(self):
        ids = [self.create({"title": f"问卷{i}"}).json()["id"] for i in range(3)]
        page = self.client.get("/api/surveys?offset=1&limit=1", headers=self.headers).json()
        self.assertEqual(page["total"], 3)
        self.assertEqual([item["id"] for item in page["items"]], [ids[1]])
        empty = self.client.get("/api/surveys?offset=10", headers=self.headers).json()
        self.assertEqual(empty["items"], [])
        for query in ["limit=0", "limit=101", "offset=-1"]:
            self.assertEqual(self.client.get("/api/surveys?" + query, headers=self.headers).status_code, 422)

    def test_input_limits_options_and_server_owned_fields(self):
        for body in [{"title": " "}, {"title": "x" * 101}, {"title": "x", "description": "x" * 1001},
                     {"title": "x", "owner_id": str(self.bob)}, {"title": "x", "status": "published"},
                     {"title": "x", "questions": []}, {"title": "x", "allow_repeat": "false"}]:
            self.assertEqual(self.create(body).status_code, 422)
        valid = self.create({"title": "x" * 100, "description": "x" * 1000,
                             "allow_repeat": True, "allow_anonymous": True})
        self.assertEqual(valid.status_code, 201)
        self.assertTrue(valid.json()["allow_repeat"])
        self.assertTrue(valid.json()["allow_anonymous"])

    def test_authentication_required(self):
        self.assertEqual(self.create(headers={}).status_code, 401)
        for url in ["/api/surveys", "/api/surveys/" + str(ObjectId())]:
            self.assertEqual(self.client.get(url).status_code, 401)

    def edit(self, identifier, body, headers=None):
        return self.client.put("/api/surveys/" + identifier, json=body,
                               headers=self.headers if headers is None else headers)

    def sample_draft(self):
        return {"title": "课程问卷（编辑）", "description": "编辑后的说明",
                "allow_anonymous": True, "allow_repeat": True, "questions": [
                    {"type": "single", "title": "是否参加", "required": True,
                     "options": [{"label": "是"}, {"label": "否"}]},
                    {"type": "multiple", "title": "喜欢的课程", "required": True,
                     "options": [{"label": "数据库"}, {"label": "编程"}, {"label": "网络"}],
                     "validation": {"min_choices": 2, "max_choices": 2}},
                    {"type": "text", "title": "建议", "validation": {"min_length": 1, "max_length": 50}},
                    {"type": "number", "title": "年龄", "validation": {"integer_only": True,
                                                                                "min_value": 0, "max_value": 120}},
                    {"type": "number", "title": "手机号",
                     "validation": {"integer_only": True, "phone_format": True}},
                ]}

    def test_edit_all_types_and_stable_ids_reorder_delete(self):
        created = self.create().json()
        saved = self.edit(created["id"], self.sample_draft())
        self.assertEqual(saved.status_code, 200, saved.text)
        body = saved.json()
        self.assertEqual(len(body["questions"]), 5)
        self.assertEqual(body["created_at"], created["created_at"])
        self.assertTrue(body["allow_repeat"])
        self.assertTrue(body["questions"][4]["validation"]["phone_format"])
        ids = [q["id"] for q in body["questions"]]
        option_ids = [option["id"] for option in body["questions"][0]["options"]]
        # 仅发送编辑字段；返回的 jump_rules 不是本轮可写字段。
        edit_body = {key: body[key] for key in ["title", "description", "allow_anonymous", "allow_repeat"]}
        edit_body["questions"] = [{key: value for key, value in question.items() if key != "jump_rules"}
                                  for question in body["questions"]]
        edit_body["questions"][0]["options"].reverse()
        edit_body["questions"].reverse()
        saved_again = self.edit(created["id"], edit_body)
        self.assertEqual(saved_again.status_code, 200, saved_again.text)
        questions = saved_again.json()["questions"]
        self.assertEqual([q["id"] for q in questions], list(reversed(ids)))
        self.assertEqual([o["id"] for o in questions[-1]["options"]], list(reversed(option_ids)))
        edit_body["questions"] = edit_body["questions"][:1]
        self.assertEqual(len(self.edit(created["id"], edit_body).json()["questions"]), 1)
        self.assertEqual(self.edit(created["id"], {"title": "空草稿", "questions": []}).status_code, 200)

    def test_invalid_question_configs_do_not_change_saved_draft(self):
        identifier = self.create().json()["id"]
        invalid = [
            {"type": "single", "title": "x", "options": [{"label": "A"}]},
            {"type": "single", "title": "x", "options": [{"label": "A"}] * 31},
            {"type": "text", "title": " "},
            {"type": "text", "title": "x" * 201},
            {"type": "text", "title": "x", "options": [{"label": "A"}]},
            {"type": "text", "title": "x", "validation": {"min_value": 1}},
            {"type": "text", "title": "x", "validation": {"min_length": -1}},
            {"type": "text", "title": "x", "validation": {"min_length": 5, "max_length": 2}},
            {"type": "number", "title": "x", "validation": {"phone_format": True}},
            {"type": "number", "title": "x", "validation": {"min_value": 20, "max_value": 10}},
            {"type": "number", "title": "x", "validation": {"min_value": True}},
            {"type": "number", "title": "x", "validation": {"integer_only": True, "min_value": 0.1, "max_value": 0.9}},
            {"type": "text", "title": "x", "required": True, "validation": {"max_length": 0}},
            {"type": "multiple", "title": "x", "options": [{"label": "A"}, {"label": "B"}],
             "validation": {"max_choices": 3}},
            {"type": "single", "title": "x", "options": [{"label": "A"}, {"label": "x" * 101}]},
        ]
        for question in invalid:
            result = self.edit(identifier, {"title": "bad", "questions": [question]})
            self.assertEqual(result.status_code, 422, result.text)
        stored = self.client.get("/api/surveys/" + identifier, headers=self.headers).json()
        self.assertEqual(stored["questions"], [])
        self.assertEqual(stored["title"], "课程问卷")

    def test_question_count_and_duplicate_foreign_ids(self):
        identifier = self.create().json()["id"]
        question = {"type": "text", "title": "建议"}
        self.assertEqual(self.edit(identifier, {"title": "上限", "questions": [question] * 100}).status_code, 200)
        self.assertEqual(self.edit(identifier, {"title": "超限", "questions": [question] * 101}).status_code, 422)
        self.assertEqual(self.edit(identifier, {"title": "x", "questions": [{**question, "id": "unknown"}]}).status_code, 422)
        body = self.edit(identifier, self.sample_draft()).json()
        first = {key: value for key, value in body["questions"][0].items() if key != "jump_rules"}
        self.assertEqual(self.edit(identifier, {"title": "重复", "questions": [first, first]}).status_code, 422)
        first["options"][1]["id"] = first["options"][0]["id"]
        self.assertEqual(self.edit(identifier, {"title": "重复选项", "questions": [first]}).status_code, 422)
        first["options"][1]["id"] = "foreign-option"
        self.assertEqual(self.edit(identifier, {"title": "未知选项", "questions": [first]}).status_code, 422)

    def test_edit_permissions_locked_states_and_invalid_ids(self):
        identifier = self.create().json()["id"]
        body = {"title": "edit", "questions": []}
        self.assertEqual(self.edit(identifier, body, headers={}).status_code, 401)
        self.assertEqual(self.edit(identifier, body, headers=self.bob_headers).status_code, 404)
        self.assertEqual(self.edit("invalid", body).status_code, 404)
        self.assertEqual(self.edit(str(ObjectId()), body).status_code, 404)
        for status in ["published", "closed"]:
            # 设置测试夹具模拟状态，不调用尚未实现的发布接口。
            self.database.surveys.update_one({"_id": ObjectId(identifier)}, {"$set": {"status": status}})
            self.assertEqual(self.edit(identifier, body).status_code, 409)
            stored = self.database.surveys.find_one({"_id": ObjectId(identifier)})
            self.assertEqual(stored["title"], "课程问卷")

    def test_atomic_edit_does_not_match_stale_snapshot(self):
        identifier = self.create().json()["id"]
        original = self.database.surveys.find_one({"_id": ObjectId(identifier)})
        self.database.surveys.update_one({"_id": ObjectId(identifier)}, {"$set": {"status": "published"}})
        result = self.database.surveys.find_one_and_update(original, {"$set": {"title": "不应覆盖"}})
        self.assertIsNone(result)
        stored = self.database.surveys.find_one({"_id": ObjectId(identifier)})
        self.assertEqual(stored["title"], "课程问卷")

    def configured_draft(self):
        identifier = self.create().json()["id"]
        return self.edit(identifier, self.sample_draft()).json()

    def rules(self, draft, source_index, rules, headers=None):
        return self.client.put(
            f"/api/surveys/{draft['id']}/questions/{draft['questions'][source_index]['id']}/jump-rules",
            json={"jump_rules": rules}, headers=self.headers if headers is None else headers,
        )

    def rule(self, operator, value, target=None):
        return {"condition": {"operator": operator, "value": value},
                "target": {"kind": "question", "question_id": target} if target else {"kind": "end"}}

    def test_configure_rules_publish_and_lock(self):
        draft = self.configured_draft()
        option = draft["questions"][0]["options"][0]["id"]
        rules = [self.rule("equals", option, draft["questions"][3]["id"])]
        self.assertEqual(self.rules(draft, 0, rules).status_code, 200)
        self.assertEqual(self.rules(draft, 0, rules, headers={}).status_code, 401)
        self.assertEqual(self.rules(draft, 0, rules, headers=self.bob_headers).status_code, 404)
        url = f"/api/surveys/{draft['id']}/publish"
        self.assertEqual(self.client.post(url, json={}, headers=self.bob_headers).status_code, 404)
        self.assertEqual(self.client.post(url, json={}).status_code, 401)
        published = self.client.post(url, json={}, headers=self.headers)
        self.assertEqual(published.status_code, 200, published.text)
        self.assertEqual(published.json()["status"], "published")
        self.assertEqual(published.json()["fill_url"], f"/survey/{draft['id']}")
        self.assertEqual(self.rules(draft, 0, []).status_code, 409)
        self.assertEqual(self.edit(draft["id"], self.sample_draft()).status_code, 409)
        self.assertEqual(self.client.post(url, json={}, headers=self.headers).status_code, 409)

    def test_reject_invalid_jump_targets_and_conditions(self):
        draft = self.configured_draft()
        q = draft["questions"]
        option = q[0]["options"][0]["id"]
        bad = [self.rule("equals", option, q[0]["id"]), self.rule("equals", option, "missing"),
               self.rule("equals", "foreign-option", q[2]["id"]), self.rule("gt", 10, q[2]["id"]),
               {"condition": {"operator": "equals", "value": option},
                "target": {"kind": "end", "question_id": q[2]["id"]}}]
        for rule in bad:
            self.assertEqual(self.rules(draft, 0, [rule]).status_code, 422)
        self.assertEqual(self.rules(draft, 2, [self.rule("eq", 1)]).status_code, 422)
        self.assertEqual(self.rules(draft, 3, [self.rule("gt", 10, q[0]["id"])]).status_code, 422)
        stored = self.client.get(f"/api/surveys/{draft['id']}", headers=self.headers).json()
        self.assertTrue(all(not item["jump_rules"] for item in stored["questions"]))

    def test_multi_and_numeric_rules_configuration(self):
        draft = self.configured_draft()
        q = draft["questions"]
        choices = [item["id"] for item in q[1]["options"]]
        rules = [self.rule("contains_all", choices[:2], q[3]["id"]), self.rule("contains", choices[0])]
        saved = self.rules(draft, 1, rules)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["questions"][1]["jump_rules"], rules)
        for value in [[], [choices[0], choices[0]], ["missing"]]:
            self.assertEqual(self.rules(draft, 1, [self.rule("contains_all", value)]).status_code, 422)
        for operator in ["gt", "gte", "lt", "lte", "eq"]:
            self.assertEqual(self.rules(draft, 3, [self.rule(operator, 18, q[4]["id"])]).status_code, 200)
        self.assertEqual(self.rules(draft, 3, [self.rule("eq", True)]).status_code, 422)

    def test_edit_preserves_rules_and_rejects_dangling_references(self):
        draft = self.configured_draft()
        option = draft["questions"][0]["options"][0]["id"]
        rules = [self.rule("equals", option, draft["questions"][3]["id"])]
        saved = self.rules(draft, 0, rules).json()
        body = {key: saved[key] for key in ["title", "description", "allow_anonymous", "allow_repeat", "questions"]}
        body["questions"][0].pop("jump_rules")
        kept = self.edit(draft["id"], body)
        self.assertEqual(kept.status_code, 200, kept.text)
        self.assertEqual(kept.json()["questions"][0]["jump_rules"], rules)
        removed = deepcopy(body)
        del removed["questions"][3]
        self.assertEqual(self.edit(draft["id"], removed).status_code, 422)
        changed_options = deepcopy(body)
        changed_options["questions"][0]["options"][0] = {"label": "新选项"}
        self.assertEqual(self.edit(draft["id"], changed_options).status_code, 422)
        removed["questions"][0]["jump_rules"] = []
        self.assertEqual(self.edit(draft["id"], removed).status_code, 200)

    def test_publish_validation_and_timezone_deadline(self):
        from datetime import datetime, timedelta, timezone
        identifier = self.create().json()["id"]
        url = f"/api/surveys/{identifier}/publish"
        self.assertEqual(self.client.post(url, json={}, headers=self.headers).status_code, 422)
        self.edit(identifier, self.sample_draft())
        for deadline in ["2020-01-01T12:00:00+08:00", "2099-01-01T12:00:00"]:
            self.assertEqual(self.client.post(url, json={"deadline": deadline}, headers=self.headers).status_code, 422)
        questions = self.database.surveys.find_one({"_id": ObjectId(identifier)})["questions"]
        broken = deepcopy(questions)
        broken[0]["jump_rules"] = [self.rule("equals", "bad-option")]
        self.database.surveys.update_one({"_id": ObjectId(identifier)}, {"$set": {"questions": broken}})
        self.assertEqual(self.client.post(url, json={}, headers=self.headers).status_code, 422)
        self.database.surveys.update_one({"_id": ObjectId(identifier)}, {"$set": {"questions": questions}})
        deadline = datetime.now(timezone(timedelta(hours=8))) + timedelta(days=1)
        published = self.client.post(url, json={"deadline": deadline.isoformat()}, headers=self.headers)
        self.assertEqual(published.status_code, 200, published.text)
        returned = datetime.fromisoformat(published.json()["deadline"].replace("Z", "+00:00"))
        expected = deadline.astimezone(timezone.utc)
        self.assertEqual(returned, expected.replace(microsecond=expected.microsecond // 1000 * 1000))

    def published_draft(self):
        draft = self.configured_draft()
        result = self.client.post(f"/api/surveys/{draft['id']}/publish", json={}, headers=self.headers)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_deadline_update_timezone_clear_and_content_unchanged(self):
        draft = self.published_draft()
        url = f"/api/surveys/{draft['id']}/deadline"
        expected = datetime.now(timezone(timedelta(hours=8))) + timedelta(days=2)
        changed = self.client.patch(url, json={"deadline": expected.isoformat()}, headers=self.headers)
        self.assertEqual(changed.status_code, 200, changed.text)
        returned = datetime.fromisoformat(changed.json()["deadline"].replace("Z", "+00:00"))
        utc = expected.astimezone(timezone.utc)
        self.assertEqual(returned, utc.replace(microsecond=utc.microsecond // 1000 * 1000))
        for key in ["questions", "title", "description", "allow_repeat", "allow_anonymous", "created_at", "status"]:
            self.assertEqual(changed.json()[key], draft[key])
        sooner = datetime.now(timezone.utc) + timedelta(days=1)
        self.assertEqual(self.client.patch(url, json={"deadline": sooner.isoformat()}, headers=self.headers).status_code, 200)
        cleared = self.client.patch(url, json={"deadline": None}, headers=self.headers)
        self.assertEqual(cleared.status_code, 200)
        self.assertIsNone(cleared.json()["deadline"])

    def test_deadline_rejects_expired_or_invalid_update(self):
        draft = self.published_draft()
        url = f"/api/surveys/{draft['id']}/deadline"
        for payload in [{}, {"deadline": "2099-01-01T12:00:00"}, {"deadline": "2020-01-01T12:00:00Z"},
                        {"deadline": None, "allow_repeat": False}]:
            self.assertEqual(self.client.patch(url, json=payload, headers=self.headers).status_code, 422)
        expired = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.database.surveys.update_one({"_id": ObjectId(draft["id"])}, {"$set": {"deadline": expired}})
        future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        for payload in [{"deadline": None}, {"deadline": future}]:
            self.assertEqual(self.client.patch(url, json=payload, headers=self.headers).status_code, 409)

    def test_close_locks_every_edit_and_reopen(self):
        draft = self.published_draft()
        url = f"/api/surveys/{draft['id']}/close"
        closed = self.client.post(url, headers=self.headers)
        self.assertEqual(closed.status_code, 200, closed.text)
        self.assertEqual(closed.json()["status"], "closed")
        self.assertEqual(closed.json()["questions"], draft["questions"])
        self.assertEqual(self.client.post(url, headers=self.headers).status_code, 409)
        self.assertEqual(self.client.patch(f"/api/surveys/{draft['id']}/deadline", json={"deadline": None}, headers=self.headers).status_code, 409)
        self.assertEqual(self.client.post(f"/api/surveys/{draft['id']}/publish", json={}, headers=self.headers).status_code, 409)
        self.assertEqual(self.edit(draft["id"], self.sample_draft()).status_code, 409)
        self.assertEqual(self.rules(draft, 0, []).status_code, 409)

    def test_management_actions_require_owner_and_published_status(self):
        draft = self.configured_draft()
        for path, method, body in [("close", "post", {}), ("deadline", "patch", {"deadline": None})]:
            url = f"/api/surveys/{draft['id']}/{path}"
            self.assertEqual(self.client.request(method, url, json=body).status_code, 401)
            self.assertEqual(self.client.request(method, url, json=body, headers=self.bob_headers).status_code, 404)
            self.assertEqual(self.client.request(method, url, json=body, headers=self.headers).status_code, 409)
            self.assertEqual(self.client.request(method, f"/api/surveys/invalid/{path}", json=body, headers=self.headers).status_code, 404)

    def test_database_time_guard_and_closing_expired_survey(self):
        draft = self.published_draft()
        expired = datetime.now(timezone.utc) - timedelta(seconds=1)
        self.database.surveys.update_one({"_id": ObjectId(draft["id"])}, {"$set": {"deadline": expired}})
        previous = self.database.surveys.find_one({"_id": ObjectId(draft["id"])})
        guard = {"$expr": {"$or": [{"$eq": ["$deadline", None]}, {"$gt": ["$deadline", "$$NOW"]}]}}
        self.assertIsNone(self.database.surveys.find_one_and_update({**previous, **guard}, {"$set": {"deadline": None}}))
        self.assertEqual(self.client.post(f"/api/surveys/{draft['id']}/close", headers=self.headers).status_code, 200)


class JumpLogicTests(unittest.TestCase):
    def test_multiselect_first_match_and_no_match(self):
        question = {"jump_rules": [
            {"condition": {"operator": "contains_all", "value": ["A", "B"]}, "target": {"kind": "question", "question_id": "q3"}},
            {"condition": {"operator": "contains", "value": "A"}, "target": {"kind": "end"}},
        ]}
        self.assertEqual(first_jump_target(question, ["A", "B", "C"])["question_id"], "q3")
        self.assertEqual(first_jump_target(question, ["A"]), {"kind": "end"})
        self.assertIsNone(first_jump_target(question, ["C"]))
        self.assertIsNone(first_jump_target(question, []))

    def test_single_numeric_zero_and_empty(self):
        question = {"jump_rules": [{"condition": {"operator": "equals", "value": "A"}, "target": {"kind": "end"}}]}
        self.assertEqual(first_jump_target(question, "A"), {"kind": "end"})
        for operator, yes, no in [("eq", 0, 1), ("gt", 1, 0), ("gte", 0, -1), ("lt", -1, 0), ("lte", 0, 1)]:
            question["jump_rules"][0]["condition"] = {"operator": operator, "value": 0}
            self.assertEqual(first_jump_target(question, yes), {"kind": "end"})
            for answer in [no, None, "", [], False]:
                self.assertIsNone(first_jump_target(question, answer))


@unittest.skipUnless(os.getenv("RUN_MONGO_TESTS") == "1", "设置 RUN_MONGO_TESTS=1 才运行真实数据库测试")
class MongoSurveyTests(SurveyTests):
    use_mongo = True


if __name__ == "__main__":
    unittest.main()
