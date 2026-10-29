"""固定版本跨问卷统计：真实提交、版本/选项隔离、最新整份及隐私。"""
import os
import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from bson import ObjectId

from tests import test_questions as question_fixtures


class GlobalStatisticsTests(unittest.TestCase):
    use_mongo = False
    setUp = question_fixtures.QuestionTests.setUp
    content = question_fixtures.QuestionTests.content
    share = question_fixtures.QuestionTests.share

    def create(self, content=None):
        q = question_fixtures.QuestionTests.create(self, content)
        self.share(q)
        return q
    new_version = question_fixtures.QuestionTests.new_version

    def survey(self, references, headers=None, *, publish=True):
        headers = headers or self.headers
        result = self.client.post("/api/surveys", headers=headers, json={
            "title": "全局统计测试", "allow_anonymous": True, "allow_repeat": True})
        self.assertEqual(result.status_code, 201, result.text)
        s = result.json()
        for q, version_id in references:
            imported = self.client.post(f"/api/surveys/{s['id']}/library-questions", headers=headers,
                json={"question_id": q["id"], "version_id": version_id})
            self.assertEqual(imported.status_code, 200, imported.text)
            s = imported.json()
        if publish:
            s = self.publish(s, headers)
        return s

    def publish(self, survey, headers=None):
        result = self.client.post(f"/api/surveys/{survey['id']}/publish", headers=headers or self.headers, json={})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def send(self, survey, answers, headers=None, anonymous=True):
        result = self.client.post(f"/api/fill/surveys/{survey['id']}/responses", headers=headers or self.bob_headers,
            json={"is_anonymous": anonymous, "answers": [{"question_id": qid, "value": value} for qid, value in answers.items()]})
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()

    def url(self, question, version=None, query=""):
        return f"/api/questions/{question['id']}/versions/{version or question['current_version_id']}/statistics" + query

    def stats(self, question, version=None, query="", headers=None):
        result = self.client.get(self.url(question, version, query), headers=headers or self.headers)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def test_latest_per_survey_cross_user_not_deduplicated_closed_and_expired(self):
        q = self.create()
        refs = [(q, q["current_version_id"])]
        a = self.survey(refs)
        b = self.survey(refs, self.bob_headers)
        self.survey(refs)  # 无有效回答，但计入引用问卷数
        self.survey(refs, publish=False)  # 草稿不计入
        self.send(a, {a["questions"][0]["id"]: 20})
        self.send(a, {a["questions"][0]["id"]: 30})
        self.send(b, {b["questions"][0]["id"]: 40})
        self.client.post(f"/api/surveys/{a['id']}/close", headers=self.headers)
        self.database.surveys.update_one({"_id": ObjectId(b["id"])}, {"$set": {"deadline": datetime.now(timezone.utc) - timedelta(days=1)}})
        result = self.stats(q, headers=self.bob_headers)
        self.assertEqual(result["referenced_survey_count"], 3)
        self.assertEqual(result["answered_survey_count"], 2)
        self.assertEqual(result["answered_count"], 2)
        self.assertEqual(result["average"], 35)
        self.assertEqual([x["value"] for x in result["distribution"]], [30, 40])
        self.assertEqual(result["counting_unit"], "valid_answer_occurrence")

    def test_single_choice_option_mapping_and_version_and_logical_id_isolation(self):
        q = self.create(self.content("同名题目", "single"))
        a = self.survey([(q, q["current_version_id"])])
        b = self.survey([(q, q["current_version_id"])], self.bob_headers)
        self.assertNotEqual(a["questions"][0]["options"][0]["id"], b["questions"][0]["options"][0]["id"])
        self.send(a, {a["questions"][0]["id"]: a["questions"][0]["options"][0]["id"]})
        self.send(b, {b["questions"][0]["id"]: b["questions"][0]["options"][1]["id"]})
        content = deepcopy(q["current_version"]["content"])
        content["options"][0]["label"] = "新版选项"
        newer = self.new_version(q, content).json()
        c = self.survey([(newer, newer["current_version_id"])])
        self.send(c, {c["questions"][0]["id"]: c["questions"][0]["options"][0]["id"]})
        other = self.create(self.content("同名题目", "single"))
        d = self.survey([(other, other["current_version_id"])])
        self.send(d, {d["questions"][0]["id"]: d["questions"][0]["options"][0]["id"]})
        result = self.stats(q)
        self.assertEqual(result["answered_count"], 2)
        self.assertEqual(result["referenced_survey_count"], 2)
        self.assertEqual([o["count"] for o in result["options"]], [1, 1])
        self.assertEqual([o["percentage"] for o in result["options"]], [50, 50])
        self.assertEqual(result["options"][0]["id"], q["current_version"]["content"]["options"][0]["id"])
        self.assertEqual(self.stats(newer)["answered_count"], 1)
        self.assertEqual(self.stats(newer)["options"][0]["label"], "新版选项")

    def test_multiple_choice_occurrence_denominator(self):
        content = self.content("方向", "multiple")
        content["options"].append({"label": "第三项"})
        q = self.create(content)
        a = self.survey([(q, q["current_version_id"])])
        b = self.survey([(q, q["current_version_id"])])
        self.send(a, {a["questions"][0]["id"]: [o["id"] for o in a["questions"][0]["options"][:2]]})
        self.send(b, {b["questions"][0]["id"]: [o["id"] for o in b["questions"][0]["options"][1:]]})
        result = self.stats(q)
        self.assertEqual(result["answered_count"], 2)
        self.assertEqual([o["count"] for o in result["options"]], [1, 2, 1])
        self.assertEqual([o["percentage"] for o in result["options"]], [50, 100, 50])

    def test_text_contents_visible_to_shared_reader_without_identity_or_response_fields(self):
        q = self.create(self.content("反馈", "text"))
        s = self.survey([(q, q["current_version_id"])])
        qid = s["questions"][0]["id"]
        receipt = self.send(s, {qid: "<script>示例</script>\n保留换行"}, anonymous=False)
        self.send(s, {qid: "另一份私密意见"}, self.headers)
        response = self.client.get(self.url(q), headers=self.bob_headers)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result["answered_count"], 2)
        self.assertEqual(result["distribution"], [])
        self.assertEqual(result["options"], [])
        self.assertCountEqual(result["text_answers"], ["<script>示例</script>\n保留换行", "另一份私密意见"])
        self.assertEqual(result["text_offset"], 0)
        self.assertEqual(result["text_limit"], 20)
        for secret in ["Alice", "Bob", str(self.alice),
                       str(self.bob), receipt["id"], qid, '"answers"', '"values"', '"latest_responses"', '"user_id"']:
            self.assertNotIn(secret, response.text)

    def test_text_latest_whole_response_pagination_duplicates_and_version_isolation(self):
        q = self.create(self.content("意见", "text"))
        refs = [(q, q["current_version_id"])]
        a = self.survey(refs)
        b = self.survey(refs)
        c = self.survey(refs)
        self.send(a, {a["questions"][0]["id"]: "旧回答不回填"})
        self.send(a, {a["questions"][0]["id"]: "相同意见"})
        self.send(b, {b["questions"][0]["id"]: "相同意见"})
        self.send(c, {c["questions"][0]["id"]: "后来清空"})
        self.send(c, {})
        newer = self.new_version(q, self.content("新版意见", "text")).json()
        d = self.survey([(newer, newer["current_version_id"])])
        self.send(d, {d["questions"][0]["id"]: "只属于新版"})
        for offset in [0, 1]:
            page = self.stats(q, query=f"?offset={offset}&limit=1")
            self.assertEqual(page["answered_count"], 2)
            self.assertEqual(page["text_answers"], ["相同意见"])
            self.assertEqual(page["text_offset"], offset)
            self.assertEqual(page["text_limit"], 1)
        self.assertEqual(self.stats(q)["text_answers"], ["相同意见", "相同意见"])
        self.assertEqual(self.stats(q, query="?offset=99")["text_answers"], [])
        self.assertEqual(self.stats(newer)["text_answers"], ["只属于新版"])
        for query in ["?offset=-1", "?limit=0", "?limit=101"]:
            self.assertEqual(self.client.get(self.url(q, query=query), headers=self.headers).status_code, 422)

    def test_text_permissions_used_version_after_bank_deletion_and_multiple_positions(self):
        q = self.create(self.content("建议", "text"))
        s = self.survey([(q, q["current_version_id"])] * 2, self.bob_headers)
        first, second = s["questions"]
        self.send(s, {first["id"]: "第一处", second["id"]: "第二处"})
        self.assertEqual(self.stats(q, headers=self.bob_headers)["text_answers"], ["第一处", "第二处"])
        self.assertEqual(self.client.get(self.url(q)).status_code, 401)
        newer = self.new_version(q, self.content("新版建议", "text")).json()
        bank = self.client.get('/api/question-banks', headers=self.headers).json()['items'][0]
        self.client.delete(f"/api/question-banks/{bank['id']}?expected_revision={bank['revision']}", headers=self.headers)
        self.assertEqual(self.stats(q, headers=self.bob_headers)["text_answers"], ["第一处", "第二处"])
        self.assertEqual(self.client.get(self.url(newer), headers=self.bob_headers).status_code, 404)

    def test_latest_skipped_and_optional_null_no_historical_backfill_zero_counted(self):
        control = self.create(self.content("继续吗", "single"))
        number = self.create()
        s = self.survey([(control, control["current_version_id"]), (number, number["current_version_id"])], publish=False)
        first, age = s["questions"]
        rule = {"jump_rules": [{"condition": {"operator": "equals", "value": first["options"][1]["id"]}, "target": {"kind": "end"}}]}
        self.assertEqual(self.client.put(f"/api/surveys/{s['id']}/questions/{first['id']}/jump-rules", headers=self.headers, json=rule).status_code, 200)
        s = self.publish(s)
        self.send(s, {first["id"]: first["options"][0]["id"], age["id"]: 9})
        self.send(s, {first["id"]: first["options"][1]["id"]})
        self.send(s, {first["id"]: first["options"][0]["id"], age["id"]: 0}, self.headers)
        result = self.stats(number)
        self.assertEqual(result["answered_count"], 1)
        self.assertEqual(result["average"], 0)
        self.assertEqual(result["distribution"][0]["value"], 0)
        self.send(s, {first["id"]: first["options"][0]["id"]}, self.headers)
        result = self.stats(number)
        self.assertEqual(result["answered_count"], 0)
        self.assertEqual(result["answered_survey_count"], 0)
        self.assertIsNone(result["average"])

    def test_text_latest_skipped_does_not_return_historical_answer(self):
        control = self.create(self.content("继续吗", "single"))
        text = self.create(self.content("意见", "text"))
        s = self.survey([(control, control["current_version_id"]), (text, text["current_version_id"])], publish=False)
        first, opinion = s["questions"]
        rule = {"jump_rules": [{"condition": {"operator": "equals", "value": first["options"][1]["id"]}, "target": {"kind": "end"}}]}
        self.assertEqual(self.client.put(f"/api/surveys/{s['id']}/questions/{first['id']}/jump-rules", headers=self.headers, json=rule).status_code, 200)
        s = self.publish(s)
        self.send(s, {first["id"]: first["options"][0]["id"], opinion["id"]: "历史意见"})
        self.send(s, {first["id"]: first["options"][1]["id"]})
        result = self.stats(text)
        self.assertEqual(result["answered_count"], 0)
        self.assertEqual(result["text_answers"], [])

    def test_same_version_multiple_positions_count_separately(self):
        q = self.create()
        s = self.survey([(q, q["current_version_id"]), (q, q["current_version_id"])])
        first, second = s["questions"]
        self.send(s, {first["id"]: 20, second["id"]: 40})
        result = self.stats(q)
        self.assertEqual(result["referenced_survey_count"], 1)
        self.assertEqual(result["answered_survey_count"], 1)
        self.assertEqual(result["answered_count"], 2)
        self.assertEqual(result["average"], 30)
        self.send(s, {first["id"]: None, second["id"]: 10})
        self.assertEqual(self.stats(q)["answered_count"], 1)

    def test_numeric_distribution_pagination_and_global_denominator(self):
        q = self.create()
        for value in [10, 0, 20, 10]:
            s = self.survey([(q, q["current_version_id"])])
            self.send(s, {s["questions"][0]["id"]: value})
        result = self.stats(q, query="?offset=1&limit=1")
        self.assertEqual(result["distribution_total"], 3)
        self.assertEqual(result["distribution"], [{"value": 10, "count": 2, "percentage": 50}])
        self.assertEqual(result["answered_count"], 4)
        self.assertEqual(result["average"], 10)
        self.assertEqual(self.stats(q, query="?offset=99")["distribution"], [])
        for query in ["?limit=0", "?limit=101", "?offset=-1"]:
            self.assertEqual(self.client.get(self.url(q, query=query), headers=self.headers).status_code, 422)

    def test_permissions_bank_removed_retains_used_version_and_no_survey_management_rights(self):
        q = self.create()
        s = self.survey([(q, q["current_version_id"])], self.bob_headers)
        self.send(s, {s["questions"][0]["id"]: 25})
        self.assertEqual(self.stats(q, headers=self.bob_headers)["answered_count"], 1)
        self.assertEqual(self.client.get(self.url(q)).status_code, 401)
        self.assertEqual(self.client.get(f"/api/surveys/{s['id']}/statistics", headers=self.headers).status_code, 404)
        bank = self.client.get('/api/question-banks', headers=self.headers).json()['items'][0]
        self.client.delete(f"/api/question-banks/{bank['id']}?expected_revision={bank['revision']}", headers=self.headers)
        self.assertEqual(self.client.get(self.url(q), headers=self.bob_headers).status_code, 200)
        self.assertEqual(self.stats(q)["answered_count"], 1)
        self.assertEqual(self.client.get(f"/api/surveys/{s['id']}/statistics", headers=self.bob_headers).status_code, 200)
        other = self.create()
        self.assertEqual(self.client.get(self.url(q, other["current_version_id"]), headers=self.headers).status_code, 404)

    def test_empty_draft_only_and_temporary_question_exclusion(self):
        q = self.create()
        self.assertEqual(self.stats(q)["referenced_survey_count"], 0)
        self.survey([(q, q["current_version_id"])], publish=False)
        self.assertEqual(self.stats(q)["referenced_survey_count"], 0)
        s = self.survey([(q, q["current_version_id"])], publish=False)
        body = {key: s[key] for key in ["title", "description", "allow_anonymous", "allow_repeat", "questions"]}
        body["questions"].append({"type": "number", "title": q["current_version"]["content"]["title"], "required": False})
        saved = self.client.put(f"/api/surveys/{s['id']}", headers=self.headers, json=body).json()
        s = self.publish(saved)
        self.send(s, {s["questions"][1]["id"]: 100})
        result = self.stats(q)
        self.assertEqual(result["referenced_survey_count"], 1)
        self.assertEqual(result["answered_count"], 0)
        self.assertEqual(result["average_display"], "暂无数据")
        local = self.client.get(f"/api/surveys/{s['id']}/statistics", headers=self.headers).json()
        self.assertEqual(local["questions"][1]["average"], 100)

    def test_time_tie_and_finite_large_number_mean(self):
        q = self.create({"type": "number", "title": "大数", "options": [], "validation": {}})
        s = self.survey([(q, q["current_version_id"])])
        qid = s["questions"][0]["id"]
        a = self.send(s, {qid: 1e308})
        b = self.send(s, {qid: 1.7e308})
        self.send(s, {qid: 1.7e308}, self.headers)
        fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for receipt in [a, b]:
            self.database.responses.update_one({"_id": ObjectId(receipt["id"])}, {"$set": {"submitted_at": fixed}})
        result = self.stats(q)
        self.assertEqual(result["average"], 1.7e308)
        self.assertEqual(result["distribution"], [{"value": 1.7e308, "count": 2, "percentage": 100}])


@unittest.skipUnless(os.getenv("RUN_MONGO_TESTS") == "1", "设置RUN_MONGO_TESTS=1才运行真实MongoDB全局统计测试")
class MongoGlobalStatisticsTests(GlobalStatisticsTests):
    use_mongo = True
