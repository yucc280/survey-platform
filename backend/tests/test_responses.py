"""填写接口验证；复用现有测试的隔离环境，每项真实测试单独使用临时库。"""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Barrier

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from tests import test_surveys as survey_fixtures


class FillTests(unittest.TestCase):
    use_mongo = False
    # 只复用夹具和辅助函数，不继承已有test_*，避免重复计算旧测试数量。
    setUp = survey_fixtures.SurveyTests.setUp
    create = survey_fixtures.SurveyTests.create
    edit = survey_fixtures.SurveyTests.edit
    sample_draft = survey_fixtures.SurveyTests.sample_draft

    def survey(self, anonymous=False, repeat=False):
        identifier = self.create().json()["id"]
        body = self.sample_draft()
        body["allow_anonymous"], body["allow_repeat"] = anonymous, repeat
        edited = self.edit(identifier, body)
        self.assertEqual(edited.status_code, 200, edited.text)
        published = self.client.post(f"/api/surveys/{identifier}/publish", json={}, headers=self.headers)
        self.assertEqual(published.status_code, 200, published.text)
        return published.json()

    def answers(self, survey):
        q = survey["questions"]
        return {"answers": [
            {"question_id": q[0]["id"], "value": q[0]["options"][0]["id"]},
            {"question_id": q[1]["id"], "value": [o["id"] for o in q[1]["options"][:2]]},
            {"question_id": q[2]["id"], "value": "  课程很好  "},
            {"question_id": q[3]["id"], "value": "0"},
            {"question_id": q[4]["id"], "value": "13800138000"},
        ]}

    def endpoint(self, survey, suffix=""):
        return f"/api/fill/surveys/{survey['id']}" + suffix

    def test_fill_read_login_and_private_fields(self):
        draft = self.create().json()
        self.assertEqual(self.client.get(self.endpoint(draft), headers=self.bob_headers).status_code, 404)
        survey = self.survey()
        self.assertEqual(self.client.get(self.endpoint(survey)).status_code, 401)
        result = self.client.get(self.endpoint(survey), headers=self.bob_headers)
        self.assertEqual(result.status_code, 200)
        self.assertNotIn("owner_id", result.json())
        self.assertNotIn("user_id", result.json())
        self.assertNotIn("responses", result.json())
        self.assertEqual(len(result.json()["questions"]), 5)
        self.assertEqual(self.client.get("/api/fill/surveys/bad-id", headers=self.headers).status_code, 404)

    def test_validation_no_save_and_submission_canonical_values(self):
        survey = self.survey()
        body = self.answers(survey)
        checked = self.client.post(self.endpoint(survey, "/validate"), json=body, headers=self.bob_headers)
        self.assertEqual(checked.status_code, 200, checked.text)
        self.assertEqual(self.database.responses.count_documents({}), 0)
        self.assertEqual(checked.json()["answers"][2]["value"], "课程很好")
        self.assertEqual(checked.json()["answers"][3]["value"], 0)
        self.assertEqual(checked.json()["answers"][4]["value"], 13800138000)
        sent = self.client.post(self.endpoint(survey, "/responses"), json=body, headers=self.bob_headers)
        self.assertEqual(sent.status_code, 201, sent.text)
        self.assertNotIn("user_id", sent.json())
        stored = self.database.responses.find_one({"_id": ObjectId(sent.json()["id"])})
        self.assertEqual(stored["user_id"], self.bob)
        self.assertTrue(stored["single_submission"])
        self.assertEqual(stored["answers"], checked.json()["answers"])
        self.assertEqual(self.client.post(self.endpoint(survey, "/responses"), json=body, headers=self.bob_headers).status_code, 409)
        self.assertEqual(self.client.get(self.endpoint(survey), headers=self.bob_headers).status_code, 409)
        # 不同账号可以独立填写。
        self.assertEqual(self.client.post(self.endpoint(survey, "/responses"), json=body, headers=self.headers).status_code, 201)

    def test_answer_validation_and_phone_format(self):
        survey = self.survey()
        original = self.answers(survey)
        cases = [(0, ""), (0, "missing-option"), (1, [survey["questions"][1]["options"][0]["id"]] * 2),
                 (1, [survey["questions"][1]["options"][0]["id"]]), (2, "字" * 51), (2, 100),
                 (3, -1), (3, 121), (3, 1.5), (3, "1.0000000000000000001"), (3, True), (3, []),
                 (4, "+8613800138000"), (4, " 13800138000"), (4, "12800138000"),
                 (4, "1380013800"), (4, "138-0013-8000"), (4, 13800138000.0)]
        for index, value in cases:
            body = deepcopy(original)
            body["answers"][index]["value"] = value
            result = self.client.post(self.endpoint(survey, "/responses"), json=body, headers=self.bob_headers)
            self.assertEqual(result.status_code, 422, result.text)
        self.assertEqual(self.database.responses.count_documents({}), 0)
        for age in [0, 120, "20.0"]:
            body = deepcopy(original)
            body["answers"][3]["value"] = age
            self.assertEqual(self.client.post(self.endpoint(survey, "/validate"), json=body, headers=self.headers).status_code, 200)

    def test_single_jump_skips_required_and_rejects_old_answers(self):
        identifier = self.create().json()["id"]
        edited = self.edit(identifier, self.sample_draft()).json()
        q = edited["questions"]
        rules = [
            {"condition": {"operator": "equals", "value": q[0]["options"][0]["id"]},
             "target": {"kind": "question", "question_id": q[4]["id"]}},
            {"condition": {"operator": "equals", "value": q[0]["options"][1]["id"]}, "target": {"kind": "end"}},
        ]
        self.client.put(f"/api/surveys/{identifier}/questions/{q[0]['id']}/jump-rules", json={"jump_rules": rules}, headers=self.headers)
        self.client.post(f"/api/surveys/{identifier}/publish", json={}, headers=self.headers)
        full = self.answers(edited)
        result = self.client.post(self.endpoint(edited, "/validate"), json=full, headers=self.bob_headers)
        self.assertEqual(result.status_code, 422)
        short = {"answers": [full["answers"][0], full["answers"][4]]}
        valid = self.client.post(self.endpoint(edited, "/validate"), json=short, headers=self.bob_headers)
        self.assertEqual(valid.status_code, 200, valid.text)
        self.assertEqual(valid.json()["question_path"], [q[0]["id"], q[4]["id"]])
        # 返回修改第一题后直接结束，旧手机号答案也必须清掉。
        short["answers"][0]["value"] = q[0]["options"][1]["id"]
        self.assertEqual(self.client.post(self.endpoint(edited, "/validate"), json=short, headers=self.bob_headers).status_code, 422)
        short["answers"] = short["answers"][:1]
        sent = self.client.post(self.endpoint(edited, "/responses"), json=short, headers=self.bob_headers)
        self.assertEqual(sent.status_code, 201, sent.text)
        self.assertEqual(len(self.database.responses.find_one({"_id": ObjectId(sent.json()["id"])})["answers"]), 1)

    def test_anonymous_default_and_repeat_independent_records(self):
        survey = self.survey(anonymous=True, repeat=True)
        body = self.answers(survey)
        first = self.client.post(self.endpoint(survey, "/responses"), json=body, headers=self.bob_headers)
        body["is_anonymous"] = False
        second = self.client.post(self.endpoint(survey, "/responses"), json=body, headers=self.bob_headers)
        self.assertEqual([first.status_code, second.status_code], [201, 201])
        self.assertTrue(first.json()["is_anonymous"])
        self.assertFalse(second.json()["is_anonymous"])
        self.assertNotEqual(first.json()["id"], second.json()["id"])
        query = {"survey_id": ObjectId(survey["id"]), "user_id": self.bob}
        self.assertEqual(self.database.responses.count_documents(query), 2)
        self.assertTrue(all(not row["single_submission"] for row in self.database.responses.find(query)))
        restricted = self.survey()
        body = self.answers(restricted)
        body["is_anonymous"] = True
        self.assertEqual(self.client.post(self.endpoint(restricted, "/responses"), json=body, headers=self.headers).status_code, 422)

    def test_close_and_deadline_after_get_prevent_submission(self):
        for expired in [False, True]:
            survey = self.survey()
            body = self.answers(survey)
            self.assertEqual(self.client.get(self.endpoint(survey), headers=self.bob_headers).status_code, 200)
            if expired:
                self.database.surveys.update_one({"_id": ObjectId(survey["id"])},
                                                 {"$set": {"deadline": datetime.now(timezone.utc) - timedelta(seconds=1)}})
            else:
                self.client.post(f"/api/surveys/{survey['id']}/close", headers=self.headers)
            self.assertEqual(self.client.get(self.endpoint(survey), headers=self.bob_headers).status_code, 409)
            for suffix in ["/validate", "/responses"]:
                self.assertEqual(self.client.post(self.endpoint(survey, suffix), json=body, headers=self.bob_headers).status_code, 409)
        self.assertEqual(self.database.responses.count_documents({}), 0)

    def test_missing_unknown_duplicate_and_owned_fields(self):
        survey = self.survey()
        base = self.answers(survey)
        cases = [deepcopy(base) for _ in range(5)]
        cases[0]["answers"] = cases[0]["answers"][1:]
        cases[1]["answers"].append({"question_id": "unknown", "value": "x"})
        cases[2]["answers"].append(deepcopy(cases[2]["answers"][0]))
        cases[3]["user_id"] = str(self.alice)
        cases[4]["single_submission"] = False
        for body in cases:
            self.assertEqual(self.client.post(self.endpoint(survey, "/responses"), json=body, headers=self.bob_headers).status_code, 422)
        for suffix in ["/validate", "/responses"]:
            self.assertEqual(self.client.post(self.endpoint(survey, suffix), json=base).status_code, 401)
        self.assertEqual(self.database.responses.count_documents({}), 0)

    def test_optional_empty_answer_is_null_not_zero(self):
        survey = self.survey()
        body = self.answers(survey)
        del body["answers"][2]
        checked = self.client.post(self.endpoint(survey, "/validate"), json=body, headers=self.bob_headers)
        self.assertEqual(checked.status_code, 200, checked.text)
        self.assertIsNone(checked.json()["answers"][2]["value"])
        self.assertEqual(checked.json()["answers"][3]["value"], 0)


@unittest.skipUnless(os.getenv("RUN_MONGO_TESTS") == "1", "设置RUN_MONGO_TESTS=1才运行真实数据库测试")
class MongoFillTests(FillTests):
    use_mongo = True

    def test_two_concurrent_submissions_only_one_saved(self):
        survey = self.survey()
        body = self.answers(survey)
        barrier = Barrier(2)

        def submit(_):
            barrier.wait(timeout=5)
            return self.client.post(self.endpoint(survey, "/responses"), json=body, headers=self.bob_headers).status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(submit, range(2)))
        self.assertEqual(sorted(statuses), [201, 409])
        query = {"survey_id": ObjectId(survey["id"]), "user_id": self.bob}
        self.assertEqual(self.database.responses.count_documents(query), 1)
        # 绕开API也不能插入第二份禁止重复的答卷，确认是数据库约束。
        row = self.database.responses.find_one(query)
        row["_id"] = ObjectId()
        with self.assertRaises(DuplicateKeyError):
            self.database.responses.insert_one(row)


if __name__ == "__main__":
    unittest.main()
