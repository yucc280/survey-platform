"""共享、题库组织与使用查询；原有问卷和版本测试继续复用。"""
import os
import unittest
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from bson import ObjectId

from tests import test_questions as question_fixtures


class SharingBankTests(unittest.TestCase):
    use_mongo = False
    setUp = question_fixtures.QuestionTests.setUp
    content = question_fixtures.QuestionTests.content
    create = question_fixtures.QuestionTests.create
    draft = question_fixtures.QuestionTests.draft
    import_into = question_fixtures.QuestionTests.import_into
    new_version = question_fixtures.QuestionTests.new_version
    edit = question_fixtures.QuestionTests.edit

    share = question_fixtures.QuestionTests.share

    def bank(self, name="基础题库"):
        result = self.client.post("/api/question-banks", headers=self.headers, json={"name": name})
        self.assertEqual(result.status_code, 201, result.text)
        return result.json()

    def add(self, bank, q, headers=None):
        return self.client.put(f"/api/question-banks/{bank['id']}/questions/{q['id']}", headers=headers or self.headers,
                               json={"expected_revision": bank["revision"]})

    def usage(self, q, headers=None, query=""):
        return self.client.get(f"/api/questions/{q['id']}/usage" + query, headers=headers or self.headers)

    def test_unshared_denied_shared_read_only_and_old_visibility_removed(self):
        q = self.create()
        path = f"/api/questions/{q['id']}"
        self.assertNotIn('is_public', q)
        self.assertEqual(self.client.get(path, headers=self.bob_headers).status_code, 404)
        bank = self.share(q)
        self.assertEqual(self.client.get(path, headers=self.bob_headers).status_code, 200)
        self.assertEqual(self.client.post(path+'/versions', headers=self.bob_headers, json={"expected_revision":0,"content":self.content()}).status_code,404)
        self.assertEqual(self.client.patch(path+'/visibility',headers=self.headers,json={"is_public":True,"expected_revision":0}).status_code,404)
        self.assertEqual(self.usage(q,self.bob_headers).status_code,200)
        self.assertEqual(self.client.get('/api/questions',headers=self.bob_headers).json()['total'],0)
        self.client.delete(f"/api/question-banks/{bank['id']}?expected_revision={bank['revision']}",headers=self.headers)
        self.assertEqual(self.client.get(path, headers=self.bob_headers).status_code,404)

    def test_own_search_literal_historical_title_and_no_public_search(self):
        q=self.create(self.content('Age.*'))
        self.new_version(q,self.content('新版标题'))
        result=self.client.get('/api/questions?keyword=age.*&limit=1',headers=self.headers)
        self.assertEqual(result.json()['total'],1)
        self.assertEqual(result.json()['items'][0]['id'],q['id'])
        self.assertEqual(self.client.get('/api/questions?keyword=[',headers=self.headers).json()['total'],0)
        self.assertEqual(self.client.get('/api/questions?scope=public',headers=self.headers).status_code,422)
        self.assertEqual(self.client.get('/api/questions?keyword=age.*',headers=self.bob_headers).json()['total'],0)

    def test_bank_id_shares_and_deletion_preserves_reference_but_blocks_reuse(self):
        q=self.create()
        bank=self.share(q)
        path=f"/api/question-banks/{bank['id']}"
        self.assertEqual(self.client.get(path,headers=self.bob_headers).json()['items'][0]['id'],q['id'])
        bob=self.client.post('/api/surveys',headers=self.bob_headers,json={"title":"Bob问卷"}).json()
        s=self.import_into(bob,q,self.bob_headers).json()
        newer=self.new_version(q).json()
        self.assertEqual(self.client.delete(path+f"?expected_revision={bank['revision']}",headers=self.bob_headers).status_code,404)
        self.assertEqual(self.client.delete(path+'?expected_revision=999',headers=self.headers).status_code,409)
        self.assertEqual(self.client.delete(path+f"?expected_revision={bank['revision']}",headers=self.headers).status_code,200)
        self.assertEqual(self.client.get(path,headers=self.bob_headers).status_code,404)
        self.assertEqual(self.import_into(bob,q,self.bob_headers).status_code,404)
        self.assertEqual(self.usage(q,self.bob_headers).status_code,200)
        history=self.client.get(f"/api/questions/{q['id']}/versions",headers=self.bob_headers).json()
        self.assertEqual([v['number'] for v in history['items']],[1])
        self.assertEqual(self.client.get(f"/api/questions/{q['id']}/versions/{newer['current_version_id']}",headers=self.bob_headers).status_code,404)
        self.assertEqual(self.client.post(f"/api/surveys/{s['id']}/publish",json={},headers=self.bob_headers).status_code,200)
        self.assertEqual(self.client.get(f"/api/fill/surveys/{s['id']}",headers=self.headers).status_code,200)

    def test_bank_create_rename_membership_and_no_question_copy(self):
        q = self.create()
        bank = self.bank(" 基础信息 ")
        self.assertEqual(bank["name"], "基础信息")
        self.assertEqual(self.client.get("/api/question-banks", headers=self.bob_headers).json()["total"], 0)
        before = deepcopy(self.database.questions.find_one({"_id": ObjectId(q["id"])}))
        added = self.add(bank, q)
        self.assertEqual(added.status_code, 200, added.text)
        added = added.json()
        repeated = self.add(added, q).json()
        self.assertEqual(repeated["question_count"], 1)
        self.assertEqual(self.add(bank, q).status_code, 409)
        renamed = self.client.patch(f"/api/question-banks/{bank['id']}", headers=self.headers,
            json={"name": "年龄题库", "expected_revision": repeated["revision"]})
        self.assertEqual(renamed.status_code, 200, renamed.text)
        detail = self.client.get(f"/api/question-banks/{bank['id']}", headers=self.headers).json()
        self.assertEqual(detail["items"][0]["id"], q["id"])
        self.assertEqual(detail["unavailable_count"], 0)
        self.assertEqual(self.database.questions.find_one({"_id": ObjectId(q["id"])}), before)
        removed = self.client.delete(f"/api/question-banks/{bank['id']}/questions/{q['id']}?expected_revision={detail['revision']}", headers=self.headers)
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(removed.json()["question_count"], 0)
        self.assertEqual(self.database.questions.find_one({"_id": ObjectId(q["id"])}), before)

    def test_bank_permissions_invalid_input_and_size_guard(self):
        q = self.create()
        bank = self.bank()
        path = f"/api/question-banks/{bank['id']}"
        self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.get(path, headers=self.bob_headers).status_code, 200)
        self.assertEqual(self.add(bank, q, self.bob_headers).status_code, 404)
        self.assertEqual(self.client.patch(path, headers=self.bob_headers, json={"name": "越权", "expected_revision": 0}).status_code, 404)
        self.assertEqual(self.client.delete(path + f"/questions/{q['id']}?expected_revision=0", headers=self.bob_headers).status_code, 404)
        for name in [" ", "x" * 101]:
            self.assertEqual(self.client.post("/api/question-banks", headers=self.headers, json={"name": name}).status_code, 422)
        self.assertEqual(self.client.get("/api/question-banks/bad", headers=self.headers).status_code, 404)
        self.assertEqual(self.client.get(path + "?limit=0", headers=self.headers).status_code, 422)
        with patch("app.questions.banks.MAX_BANK_BYTES", 1):
            self.assertEqual(self.add(bank, q).status_code, 422)
        self.assertEqual(self.client.get(path, headers=self.headers).json()["question_count"], 0)

    def test_bank_own_members_only_current_version_and_retired_filter(self):
        foreign=self.client.post('/api/questions',headers=self.bob_headers,json={"content":self.content()}).json()
        q=self.create()
        bank=self.bank()
        self.assertEqual(self.add(bank,foreign).status_code,404)
        bank=self.add(bank,q).json()
        newer=self.new_version(q).json()
        path=f"/api/question-banks/{bank['id']}"
        self.assertEqual(self.client.get(path,headers=self.bob_headers).json()['items'][0]['current_version_id'],newer['current_version_id'])
        self.assertEqual(self.client.post(f"/api/questions/{q['id']}/temporary",json={"expected_revision":newer['revision']},headers=self.headers).status_code,200)
        hidden=self.client.get(path,headers=self.bob_headers).json()
        self.assertEqual(hidden['items'],[])
        self.assertEqual(hidden['unavailable_count'],1)

    def test_usage_privacy_versions_filter_and_owner_only_management(self):
        q = self.create()
        self.share(q)
        own_draft = self.draft()
        own_draft["title"] = "Alice秘密草稿"
        own_draft = self.import_into(self.edit(own_draft).json(), q).json()
        bob_draft = self.client.post("/api/surveys", headers=self.bob_headers, json={"title": "Bob秘密草稿"}).json()
        bob_draft = self.import_into(bob_draft, q, self.bob_headers).json()
        public = self.client.post("/api/surveys", headers=self.bob_headers, json={"title": "Bob发布问卷"}).json()
        public = self.import_into(public, q, self.bob_headers).json()
        self.client.post(f"/api/surveys/{public['id']}/publish", json={}, headers=self.bob_headers)
        second = self.new_version(q).json()
        latest = self.import_into(self.draft(), second).json()
        self.client.post(f"/api/surveys/{latest['id']}/publish", json={}, headers=self.headers)
        self.client.post(f"/api/surveys/{latest['id']}/close", headers=self.headers)
        for headers, forbidden, expected in [(self.headers, "Bob秘密草稿", 3), (self.bob_headers, own_draft["title"], 3)]:
            result = self.usage(q, headers)
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()["total"], expected)
            self.assertNotIn(forbidden, result.text)
            hidden_id = bob_draft["id"] if headers == self.headers else own_draft["id"]
            self.assertNotIn(hidden_id, result.text)
            for row in result.json()["items"]:
                self.assertEqual(set(row), {"survey_id", "title", "status", "creator_username", "versions"})
        filtered = self.usage(q, query=f"?version_id={q['current_version_id']}").json()
        self.assertEqual(filtered["total"], 2)
        self.assertTrue(all(row["versions"] == [{"version_id": q["current_version_id"], "version_number": 1}] for row in filtered["items"]))
        self.assertEqual(self.usage(q, query="?limit=1&offset=1").json()["total"], 3)
        self.assertEqual(self.usage(q, query="?version_id=foreign").status_code, 404)
        self.assertEqual(self.client.get(f"/api/surveys/{public['id']}", headers=self.headers).status_code, 404)

    def test_usage_elem_match_same_reference_and_delete_draft_disappears(self):
        q = self.create()
        other = self.create(self.content("另一题"))
        s = self.import_into(self.draft(), q).json()
        s = self.import_into(s, other).json()
        # 混合引用不能让题目ID与别的题版本ID分别匹配。
        q2 = self.new_version(q).json()
        self.assertEqual(self.usage(q, query=f"?version_id={q2['current_version_id']}").json()["total"], 0)
        self.assertEqual(self.usage(other).json()["total"], 1)
        self.assertEqual(self.client.delete(f"/api/surveys/{s['id']}", headers=self.headers).status_code, 200)
        self.assertEqual(self.usage(q).json()["total"], 0)
        self.assertEqual(self.usage(other).json()["total"], 0)
        self.assertEqual(self.database.questions.count_documents({}), 2)

    def test_usage_new_reference_after_read_retains_version_metadata(self):
        q = self.create()
        before = self.database.questions.find_one({"_id": ObjectId(q["id"])})
        newer = self.new_version(q).json()
        self.import_into(self.draft(), newer)
        with patch("app.questions.api.accessible_question", return_value=before):
            result = self.usage(q)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["items"][0]["versions"], [
            {"version_id": newer["current_version_id"], "version_number": 2}])


@unittest.skipUnless(os.getenv("RUN_MONGO_TESTS") == "1", "设置RUN_MONGO_TESTS=1才运行真实MongoDB共享题库测试")
class MongoSharingBankTests(SharingBankTests):
    use_mongo = True

    def test_concurrent_bank_updates_one_wins(self):
        bank = self.bank()
        q = self.create()
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _: self.add(bank, q).status_code, range(2)))
        self.assertCountEqual(statuses, [200, 409])
        detail = self.client.get(f"/api/question-banks/{bank['id']}", headers=self.headers).json()
        self.assertEqual(detail["question_count"], 1)
