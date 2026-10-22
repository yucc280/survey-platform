"""统计API验收：同组用例分别对内存替身与独立MongoDB临时库运行。"""
import os
import unittest
from datetime import datetime, timezone

from bson import ObjectId

from tests import test_responses as fill_fixtures


class StatisticsTests(unittest.TestCase):
    use_mongo = False
    setUp = fill_fixtures.FillTests.setUp
    create = fill_fixtures.FillTests.create
    edit = fill_fixtures.FillTests.edit
    sample_draft = fill_fixtures.FillTests.sample_draft
    survey = fill_fixtures.FillTests.survey
    answers = fill_fixtures.FillTests.answers
    endpoint = fill_fixtures.FillTests.endpoint

    def stats_url(self, survey):
        return f"/api/surveys/{survey['id']}/statistics"

    def send(self, survey, body, headers=None):
        result = self.client.post(self.endpoint(survey, "/responses"), json=body,
                                  headers=self.bob_headers if headers is None else headers)
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()

    def test_latest_whole_response_choice_counts_and_average(self):
        survey = self.survey(repeat=True)
        q = survey["questions"]
        body = self.answers(survey)
        body["answers"][3]["value"] = 20
        self.send(survey, body)
        body["answers"][0]["value"] = q[0]["options"][1]["id"]
        body["answers"][1]["value"] = [q[1]["options"][1]["id"], q[1]["options"][2]["id"]]
        body["answers"][2]["value"] = "最新内容"
        body["answers"][3]["value"] = 40
        self.send(survey, body)
        alice = self.answers(survey)
        alice["answers"][3]["value"] = 20
        self.send(survey, alice, self.headers)
        result = self.client.get(self.stats_url(survey), headers=self.headers)
        self.assertEqual(result.status_code, 200, result.text)
        stats = result.json()
        self.assertEqual(stats["total_submissions"], 3)
        self.assertEqual(stats["participant_count"], 2)
        self.assertEqual([o["count"] for o in stats["questions"][0]["options"]], [1, 1])
        self.assertEqual([o["count"] for o in stats["questions"][1]["options"]], [1, 2, 1])
        self.assertCountEqual(stats["questions"][2]["values"], ["课程很好", "最新内容"])
        self.assertEqual(stats["questions"][3]["average"], 30)
        self.assertEqual(stats["questions"][3]["answered_count"], 2)
        self.assertCountEqual([row["username"] for row in stats["latest_responses"]], ["Alice", "Bob"])

    def test_anonymous_latest_hides_identity_and_internal_fields(self):
        survey = self.survey(anonymous=True, repeat=True)
        body = self.answers(survey)
        body["is_anonymous"] = False
        self.send(survey, body)
        body["is_anonymous"] = True
        receipt = self.send(survey, body)
        response = self.client.get(self.stats_url(survey), headers=self.headers)
        stats = response.json()
        self.assertEqual(stats["total_submissions"], 2)
        self.assertEqual(stats["participant_count"], 1)
        self.assertIsNone(stats["latest_responses"][0]["username"])
        self.assertTrue(stats["latest_responses"][0]["is_anonymous"])
        for private in [str(self.bob), "Bob", receipt["id"], '"user_id"', '"single_submission"', '"password_hash"']:
            self.assertNotIn(private, response.text)
        # 匿名之后再实名，只按最新答卷展示该账号名，不返回历史匿名关联。
        body["is_anonymous"] = False
        self.send(survey, body)
        stats = self.client.get(self.stats_url(survey), headers=self.headers).json()
        self.assertEqual(stats["participant_count"], 1)
        self.assertEqual(len(stats["latest_responses"]), 1)
        self.assertEqual(stats["latest_responses"][0]["username"], "Bob")

    def test_empty_stats_and_optional_null_excluded_but_zero_counted(self):
        survey = self.survey()
        empty = self.client.get(self.stats_url(survey), headers=self.headers).json()
        self.assertEqual(empty["total_submissions"], 0)
        self.assertEqual(empty["participant_count"], 0)
        self.assertEqual(empty["latest_responses"], [])
        self.assertIsNone(empty["questions"][3]["average"])
        self.assertEqual(empty["questions"][3]["average_display"], "暂无数据")
        self.assertTrue(all(o["count"] == 0 for o in empty["questions"][0]["options"]))
        body = self.answers(survey)
        del body["answers"][2]
        self.send(survey, body)
        stats = self.client.get(self.stats_url(survey), headers=self.headers).json()
        self.assertEqual(stats["questions"][2]["answered_count"], 0)
        self.assertEqual(stats["questions"][2]["values"], [])
        self.assertEqual(stats["questions"][3]["answered_count"], 1)
        self.assertEqual(stats["questions"][3]["average"], 0)
        self.assertEqual(stats["participant_count"], 1)

    def test_latest_path_does_not_fill_skipped_question_from_history(self):
        identifier = self.create().json()["id"]
        body = self.sample_draft()
        body["allow_repeat"] = True
        draft = self.edit(identifier, body).json()
        q = draft["questions"]
        rule = {"condition": {"operator": "equals", "value": q[0]["options"][1]["id"]}, "target": {"kind": "end"}}
        self.client.put(f"/api/surveys/{identifier}/questions/{q[0]['id']}/jump-rules", json={"jump_rules": [rule]}, headers=self.headers)
        self.client.post(f"/api/surveys/{identifier}/publish", json={}, headers=self.headers)
        self.send(draft, self.answers(draft))
        self.send(draft, {"answers": [{"question_id": q[0]["id"], "value": q[0]["options"][1]["id"]}]})
        stats = self.client.get(self.stats_url(draft), headers=self.headers).json()
        self.assertEqual(stats["total_submissions"], 2)
        self.assertEqual(stats["questions"][1]["answered_count"], 0)
        self.assertEqual(stats["questions"][3]["answered_count"], 0)
        self.assertIsNone(stats["questions"][3]["average"])

    def test_only_owner_and_single_question_scope(self):
        survey = self.survey()
        self.send(survey, self.answers(survey))
        qid = survey["questions"][3]["id"]
        single_url = f"/api/surveys/{survey['id']}/questions/{qid}/statistics"
        for url in [self.stats_url(survey), single_url]:
            self.assertEqual(self.client.get(url).status_code, 401)
            self.assertEqual(self.client.get(url, headers=self.bob_headers).status_code, 404)
        single = self.client.get(single_url, headers=self.headers)
        self.assertEqual(single.status_code, 200, single.text)
        self.assertEqual(single.json()["question"]["question_id"], qid)
        self.assertEqual(single.json()["question"]["average"], 0)
        self.assertTrue(all(len(row["answers"]) == 1 and row["answers"][0]["question_id"] == qid
                            for row in single.json()["latest_responses"]))
        self.assertEqual(self.client.get(f"/api/surveys/{survey['id']}/questions/missing/statistics", headers=self.headers).status_code, 404)
        self.assertEqual(self.client.get("/api/surveys/invalid/statistics", headers=self.headers).status_code, 404)

    def test_tie_break_by_id_closed_stats_and_survey_isolation(self):
        survey = self.survey(repeat=True)
        body = self.answers(survey)
        first = self.send(survey, body)
        body["answers"][3]["value"] = 60
        second = self.send(survey, body)
        fixed = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for receipt in [first, second]:
            self.database.responses.update_one({"_id": ObjectId(receipt["id"])}, {"$set": {"submitted_at": fixed}})
        # 另一个问卷的答卷不能污染当前统计。
        other = self.survey()
        self.send(other, self.answers(other))
        self.client.post(f"/api/surveys/{survey['id']}/close", headers=self.headers)
        stats = self.client.get(self.stats_url(survey), headers=self.headers).json()
        self.assertEqual(stats["total_submissions"], 2)
        self.assertEqual(stats["participant_count"], 1)
        self.assertEqual(stats["questions"][3]["average"], 60)


@unittest.skipUnless(os.getenv("RUN_MONGO_TESTS") == "1", "设置RUN_MONGO_TESTS=1才运行真实MongoDB统计测试")
class MongoStatisticsTests(StatisticsTests):
    use_mongo = True


if __name__ == "__main__":
    unittest.main()
