"""版本及问卷引用回归；同组用例分别在替身和随机真实MongoDB库执行。"""
import os
import unittest
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from bson import ObjectId

from tests import test_surveys as survey_fixtures


class QuestionTests(unittest.TestCase):
    use_mongo = False
    setUp = survey_fixtures.SurveyTests.setUp

    def content(self, title="年龄", kind="number"):
        return {"type": kind, "title": title,
                "options": [{"label": "是"}, {"label": "否"}] if kind in {"single", "multiple"} else [],
                "validation": {"min_value": 0, "max_value": 120, "integer_only": True} if kind == "number" else {}}

    def create(self, content=None):
        response = self.client.post("/api/questions", json={"content": content or self.content()}, headers=self.headers)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def share(self, q):
        bank = self.client.post('/api/question-banks', json={"name": "共享测试"}, headers=self.headers).json()
        result = self.client.put(f"/api/question-banks/{bank['id']}/questions/{q['id']}", json={"expected_revision": 0}, headers=self.headers)
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    def new_version(self, question, content=None):
        return self.client.post(f"/api/questions/{question['id']}/versions", headers=self.headers,
                                json={"expected_revision": question["revision"], "content": content or self.content("年龄（新版）")})

    def draft(self):
        return self.client.post("/api/surveys", json={"title": "版本测试"}, headers=self.headers).json()

    def import_into(self, survey, question, headers=None, version=None):
        return self.client.post(f"/api/surveys/{survey['id']}/library-questions", headers=headers or self.headers,
                                json={"question_id": question["id"], "version_id": version or question["current_version_id"]})

    def edit(self, survey):
        return self.client.put(f"/api/surveys/{survey['id']}", headers=self.headers,
                               json={key: survey[key] for key in ["title", "description", "allow_anonymous", "allow_repeat", "questions"]})

    def test_versions_restore_and_monotonic_number(self):
        q = self.create()
        v1 = deepcopy(q["current_version"])
        v2 = self.new_version(q).json()
        v3 = self.new_version(v2, self.content("第三版")).json()
        restore = self.client.patch(f"/api/questions/{q['id']}/current-version", headers=self.headers,
                                    json={"expected_revision": v3["revision"], "version_id": v1["id"]})
        self.assertEqual(restore.status_code, 200, restore.text)
        restored = restore.json()
        self.assertEqual(restored["max_version"], 3)
        self.assertEqual(restored["current_version"], v1)
        v4 = self.new_version(restored).json()
        self.assertEqual(v4["current_version"]["number"], 4)
        self.assertEqual(v4["current_version"]["parent_version_id"], v1["id"])
        history = self.client.get(f"/api/questions/{q['id']}/versions", headers=self.headers).json()
        self.assertEqual([v["number"] for v in history["items"]], [4, 3, 2, 1])
        self.assertEqual(history["items"][-1], v1)

    def test_configuration_four_types_and_forbidden_fields(self):
        for kind in ["single", "multiple", "text", "number"]:
            q = self.create(self.content(kind, kind))
            self.assertNotIn("required", q["current_version"]["content"])
            self.assertNotIn("jump_rules", q["current_version"]["content"])
        invalids = [
            {**self.content(), "required": True}, {**self.content(), "jump_rules": []},
            {**self.content(), "title": " "}, {**self.content(), "type": "matrix"},
            {**self.content(), "validation": {"min_value": 5, "max_value": 1}},
            {**self.content(), "validation": {"max_value": 2 ** 80}},
            {**self.content("x", "single"), "options": [{"id": "foreign", "label": "x"}, {"label": "y"}]},
        ]
        for content in invalids:
            result = self.client.post("/api/questions", headers=self.headers, json={"content": content})
            self.assertEqual(result.status_code, 422, result.text)

    def test_owner_access_bank_sharing_and_unshared_denial(self):
        q = self.create()
        url = f"/api/questions/{q['id']}"
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.get(url, headers=self.bob_headers).status_code, 404)
        bank = self.share(q)
        self.assertEqual(self.client.get(url, headers=self.bob_headers).status_code, 200)
        self.assertEqual(self.client.get("/api/questions", headers=self.bob_headers).json()["total"], 0)
        result = self.client.post(url + "/versions", headers=self.bob_headers,
                                  json={"content": self.content(), "expected_revision": 0})
        self.assertEqual(result.status_code, 404)
        self.assertEqual(self.client.patch(url + "/current-version", headers=self.bob_headers,
            json={"version_id": q["current_version_id"], "expected_revision": 0}).status_code, 404)
        self.client.delete(f"/api/question-banks/{bank['id']}?expected_revision={bank['revision']}", headers=self.headers)
        for suffix in ["", "/versions", f"/versions/{q['current_version_id']}"]:
            self.assertEqual(self.client.get(url + suffix, headers=self.bob_headers).status_code, 404)
        self.assertEqual(self.client.get(url, headers=self.headers).status_code, 200)

    def test_revision_conflict_size_guard_and_foreign_version(self):
        q = self.create()
        self.assertEqual(self.new_version(q).status_code, 201)
        self.assertEqual(self.new_version(q).status_code, 409)
        current = self.client.get(f"/api/questions/{q['id']}", headers=self.headers).json()
        with patch("app.questions.logic.MAX_QUESTION_BYTES", 1):
            self.assertEqual(self.new_version(current).status_code, 422)
        self.assertEqual(self.client.get(f"/api/questions/{q['id']}", headers=self.headers).json(), current)
        other = self.create()
        self.assertEqual(self.client.patch(f"/api/questions/{q['id']}/current-version", headers=self.headers,
            json={"expected_revision": current["revision"], "version_id": other["current_version_id"]}).status_code, 404)

    def test_pagination_ids_and_version_option_stability(self):
        q = self.create(self.content("原题", "single"))
        content = deepcopy(q["current_version"]["content"])
        content["title"] = "改文字"
        content["options"][0]["label"] = "修改选项文字"
        newer = self.new_version(q, content)
        self.assertEqual(newer.status_code, 201, newer.text)
        self.assertEqual(newer.json()["current_version"]["content"]["options"][0]["id"], content["options"][0]["id"])
        rows = self.client.get(f"/api/questions/{q['id']}/versions?offset=1&limit=1", headers=self.headers).json()
        self.assertEqual(rows["items"][0]["number"], 1)
        self.assertEqual(rows["total"], 2)
        for url in ["/api/questions?limit=0", "/api/questions?offset=-1", f"/api/questions/{q['id']}/versions?limit=101"]:
            self.assertEqual(self.client.get(url, headers=self.headers).status_code, 422)
        self.assertEqual(self.client.get("/api/questions/invalid", headers=self.headers).status_code, 404)

    def test_snapshot_required_is_per_survey_and_mixed_temporary_questions(self):
        q = self.create()
        first = self.import_into(self.draft(), q)
        self.assertEqual(first.status_code, 200, first.text)
        s = first.json()
        self.assertEqual(s["questions"][0]["source"]["version_id"], q["current_version_id"])
        s["questions"][0]["required"] = True
        s["questions"].append({"type": "text", "title": "临时意见", "required": False})
        saved = self.edit(s)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertTrue(saved.json()["questions"][0]["required"])
        self.assertNotIn("source", saved.json()["questions"][1])
        second = self.import_into(self.draft(), q).json()
        self.assertFalse(second["questions"][0]["required"])
        self.assertNotEqual(second["questions"][0]["id"], s["questions"][0]["id"])
        self.assertEqual(self.new_version(q).status_code, 201)
        read = self.client.get(f"/api/surveys/{s['id']}", headers=self.headers).json()
        self.assertEqual(read["questions"][0]["title"], "年龄")

    def test_reference_tampering_and_source_stripping_rejected(self):
        q = self.create(self.content("是否", "single"))
        s = self.import_into(self.draft(), q).json()
        for change in ["title", "source", "mapping", "label", "validation"]:
            body = deepcopy(s)
            item = body["questions"][0]
            if change == "source": item.pop("source")
            elif change == "mapping": item["options"][0]["source_option_id"] = "fake"
            elif change == "label": item["options"][0]["label"] = "fake"
            elif change == "validation": item["validation"] = {"min_choices": 1}
            else: item["title"] = "fake"
            self.assertEqual(self.edit(body).status_code, 422, change)
        fabricated = self.draft()
        fabricated["questions"] = deepcopy(s["questions"])
        fabricated["questions"][0].pop("id")
        for option in fabricated["questions"][0]["options"]: option.pop("id")
        self.assertEqual(self.edit(fabricated).status_code, 422)
        self.assertEqual(self.client.get(f"/api/surveys/{s['id']}", headers=self.headers).json(), s)

    def test_replacement_invalid_jumps_preserves_draft_and_valid_swap(self):
        q = self.create(self.content("是否", "single"))
        s = self.import_into(self.draft(), q).json()
        original = deepcopy(s["questions"][0])
        s["questions"][0]["jump_rules"] = [{"condition": {"operator": "equals", "value": original["options"][0]["id"]}, "target": {"kind": "end"}}]
        s = self.edit(s).json()
        newer = self.new_version(q, self.content("是否新版", "single")).json()
        url = f"/api/surveys/{s['id']}/questions/{original['id']}/source"
        reference = {"question_id": q["id"], "version_id": newer["current_version_id"]}
        self.assertEqual(self.client.put(url, json=reference, headers=self.headers).status_code, 422)
        self.assertEqual(self.client.get(f"/api/surveys/{s['id']}", headers=self.headers).json(), s)
        s["questions"][0]["jump_rules"] = []
        self.assertEqual(self.edit(s).status_code, 200)
        swapped = self.client.put(url, json=reference, headers=self.headers)
        self.assertEqual(swapped.status_code, 200, swapped.text)
        self.assertEqual(swapped.json()["questions"][0]["id"], original["id"])
        self.assertEqual(swapped.json()["questions"][0]["source"]["version_number"], 2)

    def test_published_snapshot_survives_restore_and_filling_statistics(self):
        q = self.create()
        s = self.import_into(self.draft(), q).json()
        qid = s["questions"][0]["id"]
        self.assertEqual(self.client.post(f"/api/surveys/{s['id']}/publish", json={}, headers=self.headers).status_code, 200)
        newer = self.new_version(q).json()
        self.client.patch(f"/api/questions/{q['id']}/current-version", headers=self.headers,
            json={"version_id": q["current_version_id"], "expected_revision": newer["revision"]})
        fill = self.client.get(f"/api/fill/surveys/{s['id']}", headers=self.bob_headers)
        self.assertEqual(fill.status_code, 200)
        self.assertEqual(fill.json()["questions"], s["questions"])
        response = self.client.post(f"/api/fill/surveys/{s['id']}/responses", headers=self.bob_headers,
                                    json={"answers": [{"question_id": qid, "value": 0}]})
        self.assertEqual(response.status_code, 201, response.text)
        stats = self.client.get(f"/api/surveys/{s['id']}/statistics", headers=self.headers).json()
        self.assertEqual(stats["questions"][0]["average"], 0)
        self.assertEqual(self.edit(s).status_code, 409)
        self.assertEqual(self.import_into(s, q).status_code, 409)
        self.assertEqual(self.client.put(f"/api/surveys/{s['id']}/questions/{qid}/source", headers=self.headers,
            json={"question_id": q["id"], "version_id": newer["current_version_id"]}).status_code, 409)

    def test_bank_deleted_old_snapshot_allowed_new_reference_denied(self):
        q = self.create()
        bank = self.share(q)
        other = self.client.post("/api/surveys", headers=self.bob_headers, json={"title": "他人草稿"}).json()
        s = self.import_into(other, q, self.bob_headers).json()
        self.client.delete(f"/api/question-banks/{bank['id']}?expected_revision={bank['revision']}", headers=self.headers)
        body = {key: s[key] for key in ["title", "description", "allow_anonymous", "allow_repeat", "questions"]}
        self.assertEqual(self.client.put(f"/api/surveys/{s['id']}", headers=self.bob_headers, json=body).status_code, 200)
        self.assertEqual(self.import_into(s, q, self.bob_headers).status_code, 404)
        self.assertEqual(self.client.post(f"/api/surveys/{s['id']}/publish", json={}, headers=self.bob_headers).status_code, 200)

    def test_required_conflict_rejected_without_altering_version(self):
        content = self.content("允许空文本", "text")
        content["validation"] = {"max_length": 0}
        q = self.create(content)
        s = self.import_into(self.draft(), q).json()
        s["questions"][0]["required"] = True
        self.assertEqual(self.edit(s).status_code, 422)
        self.assertEqual(self.client.get(f"/api/questions/{q['id']}", headers=self.headers).json(), q)

    def test_reference_owner_version_validation_and_canonical_id(self):
        q = self.create()
        draft = self.draft()
        self.assertEqual(self.import_into(draft, q, self.bob_headers).status_code, 404)
        self.assertEqual(self.import_into(draft, q, version="foreign_version").status_code, 404)
        uppercase = {**q, "id": q["id"].upper()}
        saved = self.import_into(draft, uppercase)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["questions"][0]["source"]["question_id"], q["id"])

    def test_save_temporary_question_all_types_draft_published_and_closed(self):
        for kind in ["single", "multiple", "text", "number"]:
            with self.subTest(kind=kind):
                s = self.draft()
                s["questions"] = [{**self.content("从问卷保存", kind), "required": True}]
                s = self.edit(s).json()
                item = s["questions"][0]
                if kind != "text":
                    condition = {"operator": "eq", "value": 0} if kind == "number" else {
                        "operator": "equals" if kind == "single" else "contains", "value": item["options"][0]["id"]}
                    item["jump_rules"] = [{"condition": condition, "target": {"kind": "end"}}]
                    s = self.edit(s).json()
                for state in ["draft", "published", "closed"]:
                    if state == "published":
                        self.assertEqual(self.client.post(f"/api/surveys/{s['id']}/publish", json={}, headers=self.headers).status_code, 200)
                    elif state == "closed":
                        self.assertEqual(self.client.post(f"/api/surveys/{s['id']}/close", headers=self.headers).status_code, 200)
                    before = self.database.surveys.find_one({"_id": ObjectId(s["id"])})
                    result = self.client.post(f"/api/surveys/{s['id']}/questions/{item['id']}/save-to-library", headers=self.headers)
                    self.assertEqual(result.status_code, 201, result.text)
                    q = result.json()
                    self.assertEqual(q["owner_id"], str(self.alice))
                    self.assertNotIn("is_public", q)
                    self.assertEqual(q["max_version"], 1)
                    version = q["current_version"]
                    self.assertIsNone(version["parent_version_id"])
                    content = version["content"]
                    self.assertEqual(content["type"], kind)
                    self.assertEqual(content["title"], item["title"])
                    self.assertEqual(content["validation"], item["validation"])
                    self.assertNotIn("required", content)
                    self.assertNotIn("jump_rules", content)
                    self.assertTrue({o["id"] for o in content["options"]}.isdisjoint({o["id"] for o in item["options"]}))
                    self.assertEqual([o["label"] for o in content["options"]], [o["label"] for o in item["options"]])
                    after = self.database.surveys.find_one({"_id": ObjectId(s["id"])})
                    converted = after["questions"][0]
                    self.assertEqual(converted["source"]["question_id"], q["id"])
                    self.assertEqual(converted["id"], item["id"])
                    self.assertEqual(converted["jump_rules"], item["jump_rules"])
                    self.assertEqual([o["id"] for o in converted["options"]], [o["id"] for o in item["options"]])
                    restored = self.client.post(f"/api/questions/{q['id']}/temporary", json={"expected_revision": q["revision"]}, headers=self.headers)
                    self.assertEqual(restored.status_code, 200, restored.text)
                    after = self.database.surveys.find_one({"_id": ObjectId(s["id"])})
                    self.assertEqual(after["questions"], before["questions"])

    def test_save_temporary_question_permissions_and_reference_rejection(self):
        s = self.draft()
        s["questions"] = [{**self.content(), "required": False}]
        s = self.edit(s).json()
        url = f"/api/surveys/{s['id']}/questions/{s['questions'][0]['id']}/save-to-library"
        count = self.database.questions.count_documents({})
        self.assertEqual(self.client.post(url).status_code, 401)
        self.assertEqual(self.client.post(url, headers=self.bob_headers).status_code, 404)
        self.assertEqual(self.client.post(f"/api/surveys/{s['id']}/questions/missing/save-to-library", headers=self.headers).status_code, 404)
        self.assertEqual(self.client.post("/api/surveys/invalid/questions/missing/save-to-library", headers=self.headers).status_code, 404)
        self.assertEqual(self.database.questions.count_documents({}), count)
        own = self.create()
        referenced = self.import_into(self.draft(), own).json()
        qid = referenced["questions"][0]["id"]
        count = self.database.questions.count_documents({})
        self.assertEqual(self.client.post(f"/api/surveys/{referenced['id']}/questions/{qid}/save-to-library", headers=self.headers).status_code, 409)
        self.assertEqual(self.database.questions.count_documents({}), count)

    def test_save_temporary_published_question_preserves_responses_and_stats(self):
        s = self.draft()
        s["questions"] = [{**self.content(), "required": True}]
        s = self.edit(s).json()
        qid = s["questions"][0]["id"]
        self.client.post(f"/api/surveys/{s['id']}/publish", json={}, headers=self.headers)
        sent = self.client.post(f"/api/fill/surveys/{s['id']}/responses", headers=self.bob_headers,
                               json={"answers": [{"question_id": qid, "value": 21}]})
        self.assertEqual(sent.status_code, 201, sent.text)
        stored = self.database.responses.find_one({"survey_id": ObjectId(s["id"])})
        stats_url = f"/api/surveys/{s['id']}/statistics"
        before_stats = self.client.get(stats_url, headers=self.headers).json()
        result = self.client.post(f"/api/surveys/{s['id']}/questions/{qid}/save-to-library", headers=self.headers)
        self.assertEqual(result.status_code, 201, result.text)
        self.assertEqual(self.database.responses.find_one({"survey_id": ObjectId(s["id"])}), stored)
        self.assertEqual(self.client.get(stats_url, headers=self.headers).json(), before_stats)
        read = self.client.get(f"/api/surveys/{s['id']}", headers=self.headers).json()
        reusable = result.json()
        self.assertEqual(read["questions"][0]["source"]["question_id"], reusable["id"])
        usage = self.client.get(f"/api/questions/{reusable['id']}/usage", headers=self.headers).json()
        self.assertEqual(usage["total"], 1)
        global_result = self.client.get(f"/api/questions/{reusable['id']}/versions/{reusable['current_version_id']}/statistics", headers=self.headers).json()
        self.assertEqual(global_result["answered_count"], 1)
        self.assertEqual(global_result["average"], 21)
        self.assertEqual(self.database.responses.count_documents({"survey_id": ObjectId(s["id"])}), 1)

    def test_temporary_reversion_guards_and_retired_visibility(self):
        q = self.create()
        first = self.import_into(self.draft(), q).json()
        second = self.import_into(self.draft(), q).json()
        url = f"/api/questions/{q['id']}/temporary"
        body = {"expected_revision": q["revision"]}
        self.assertEqual(self.client.post(url, json=body).status_code, 401)
        self.assertEqual(self.client.post(url, json=body, headers=self.bob_headers).status_code, 404)
        self.assertEqual(self.client.post(url, json=body, headers=self.headers).status_code, 409)
        self.client.delete(f"/api/surveys/{second['id']}", headers=self.headers)
        self.assertEqual(self.client.post(url, json={"expected_revision": 999}, headers=self.headers).status_code, 409)
        self.assertEqual(self.client.post(url, json=body, headers=self.headers).status_code, 200)
        read = self.client.get(f"/api/surveys/{first['id']}", headers=self.headers).json()
        self.assertNotIn("source", read["questions"][0])
        self.assertEqual(self.client.get(f"/api/questions/{q['id']}", headers=self.headers).status_code, 404)
        self.assertEqual(self.client.get('/api/questions', headers=self.headers).json()["total"], 0)
        self.assertEqual(self.client.get('/api/questions?scope=public', headers=self.bob_headers).status_code, 422)

    def test_conversion_choice_historical_mapping_and_reversion_preserves_statistics(self):
        for kind in ['single', 'multiple']:
            s = self.draft()
            s['questions'] = [{**self.content(kind=kind), "required": True}]
            s = self.edit(s).json()
            item = s['questions'][0]
            value = item['options'][0]['id']
            if kind == 'multiple':
                value = [value]
            self.client.post(f"/api/surveys/{s['id']}/publish", json={}, headers=self.headers)
            self.assertEqual(self.client.post(f"/api/fill/surveys/{s['id']}/responses", json={"answers": [{"question_id": item['id'], "value": value}]}, headers=self.bob_headers).status_code, 201)
            stats_url = f"/api/surveys/{s['id']}/statistics"
            before = self.client.get(stats_url, headers=self.headers).json()
            q = self.client.post(f"/api/surveys/{s['id']}/questions/{item['id']}/save-to-library", headers=self.headers).json()
            result = self.client.get(f"/api/questions/{q['id']}/versions/{q['current_version_id']}/statistics", headers=self.headers).json()
            self.assertEqual(result['answered_count'], 1)
            self.assertEqual(result['options'][0]['count'], 1)
            self.assertEqual(result['options'][0]['percentage'], 100)
            self.assertEqual(self.client.post(f"/api/questions/{q['id']}/temporary", json={"expected_revision": q['revision']}, headers=self.headers).status_code, 200)
            self.assertEqual(self.client.get(stats_url, headers=self.headers).json(), before)

    def test_conversion_stale_survey_does_not_leave_duplicate_question(self):
        from fastapi import HTTPException
        s = self.draft()
        s['questions'] = [{**self.content(), "required": False}]
        s = self.edit(s).json()
        count = self.database.questions.count_documents({})
        with patch('app.surveys.api.save_survey_changes', side_effect=HTTPException(409, 'stale')):
            result = self.client.post(f"/api/surveys/{s['id']}/questions/{s['questions'][0]['id']}/save-to-library", headers=self.headers)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.database.questions.count_documents({}), count)

    def test_unused_can_be_removed_but_foreign_sole_reference_cannot(self):
        unused = self.create()
        self.assertEqual(self.client.post(f"/api/questions/{unused['id']}/temporary", json={"expected_revision": 0}, headers=self.headers).status_code, 200)
        q = self.create()
        self.share(q)
        other = self.client.post('/api/surveys', json={"title": "他人问卷"}, headers=self.bob_headers).json()
        self.client.post(f"/api/surveys/{other['id']}/library-questions", json={"question_id": q["id"], "version_id": q["current_version_id"]}, headers=self.bob_headers)
        self.assertEqual(self.client.post(f"/api/questions/{q['id']}/temporary", json={"expected_revision": 0}, headers=self.headers).status_code, 409)


@unittest.skipUnless(os.getenv("RUN_MONGO_TESTS") == "1", "设置RUN_MONGO_TESTS=1才运行真实MongoDB题目测试")
class MongoQuestionTests(QuestionTests):
    use_mongo = True

    def test_concurrent_new_version_one_wins(self):
        q = self.create()
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _: self.new_version(q).status_code, range(2)))
        self.assertCountEqual(statuses, [201, 409])
        history = self.client.get(f"/api/questions/{q['id']}/versions", headers=self.headers).json()
        self.assertEqual(history["total"], 2)
