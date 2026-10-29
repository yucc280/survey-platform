"""通过现有API在当前配置的MongoDB中保留第二阶段演示数据；不覆盖已有账号。"""
import json

from fastapi.testclient import TestClient

from app.main import create_app

USERNAME = "stage2_demo_1028"
PASSWORD = "Stage2Demo28"


def main():
    with TestClient(create_app()) as client:
        def call(method, path, body=None, token=None):
            result = client.request(method, "/api" + path, json=body,
                                    headers={"Authorization": f"Bearer {token}"} if token else {})
            if result.status_code >= 400:
                raise RuntimeError(f"{method} {path}: {result.status_code} {result.text}")
            return result.json()

        registration = client.post("/api/auth/register", json={"username": USERNAME, "password": PASSWORD})
        if registration.status_code not in {201, 409}:
            raise RuntimeError(registration.text)
        token = call("POST", "/auth/login", {"username": USERNAME, "password": PASSWORD})["access_token"]
        existing = call("GET", "/surveys?limit=100", token=token)["items"]
        if any(s["title"] == "[第二阶段演示] 可填写的v1问卷" for s in existing):
            print(json.dumps({"message": "演示账号已有数据，本次不重复创建或覆盖", "username": USERNAME}, ensure_ascii=False))
            return

        def content(kind, title, options=None, validation=None):
            return {"type": kind, "title": title, "options": [{"label": label} for label in options or []],
                    "validation": validation or {}}

        def question(data):
            return call("POST", "/questions", {"content": data}, token)

        age_content = content("number", "[演示] 你的年龄", validation={"integer_only": True, "min_value": 0, "max_value": 120})
        age = question(age_content)
        v1 = age["current_version_id"]
        for label in ["[演示] 年龄 v2", "[演示] 年龄 v3"]:
            age = call("POST", f"/questions/{age['id']}/versions",
                       {"expected_revision": age["revision"], "content": {**age_content, "title": label}}, token)
        age = call("PATCH", f"/questions/{age['id']}/current-version",
                   {"expected_revision": age["revision"], "version_id": v1}, token)
        age = call("POST", f"/questions/{age['id']}/versions",
                   {"expected_revision": age["revision"], "content": {**age_content, "title": "[演示] 年龄 v4（基于v1）"}}, token)
        single = question(content("single", "[演示] 是否学习过数据库", ["是", "否"]))
        multiple = question(content("multiple", "[演示] 感兴趣的方向", ["数据库", "后端", "前端"], {"max_choices": 2}))
        text = question(content("text", "[演示] 学习建议", validation={"max_length": 100}))

        def survey(title, version):
            s = call("POST", "/surveys", {"title": title, "description": "第二阶段保留的演示数据，可自行填写、编辑草稿和查看统计。",
                     "allow_anonymous": True, "allow_repeat": True}, token)
            for q, v in [(single, single["current_version_id"]), (multiple, multiple["current_version_id"]),
                         (text, text["current_version_id"]), (age, version)]:
                s = call("POST", f"/surveys/{s['id']}/library-questions", {"question_id": q["id"], "version_id": v}, token)
            body = {key: s[key] for key in ["title", "description", "allow_anonymous", "allow_repeat", "questions"]}
            body["questions"][0]["required"] = True
            body["questions"][3]["required"] = True
            body["questions"].append({"type": "text", "title": "[演示] 仅属于此问卷的临时题", "required": False})
            s = call("PUT", f"/surveys/{s['id']}", body, token)
            first, _, _, last = s["questions"][:4]
            s = call("PUT", f"/surveys/{s['id']}/questions/{first['id']}/jump-rules", {"jump_rules": [{
                "condition": {"operator": "equals", "value": first["options"][1]["id"]},
                "target": {"kind": "question", "question_id": last["id"]}}]}, token)
            return s

        draft = survey("[第二阶段演示] 可编辑的v4草稿", age["current_version_id"])
        published = survey("[第二阶段演示] 可填写的v1问卷", v1)
        call("POST", f"/surveys/{published['id']}/publish", {}, token)
        q = published["questions"]
        for value in [19, 22]:
            call("POST", f"/fill/surveys/{published['id']}/responses", {"is_anonymous": True, "answers": [
                {"question_id": q[0]["id"], "value": q[0]["options"][0]["id"]},
                {"question_id": q[1]["id"], "value": [q[1]["options"][0]["id"]]},
                {"question_id": q[2]["id"], "value": "希望增加实践练习"},
                {"question_id": q[3]["id"], "value": value}]}, token)
        stats = call("GET", f"/surveys/{published['id']}/statistics", token=token)
        print(json.dumps({"database": client.app.state.db.name, "username": USERNAME,
                          "question_count": 4, "age_question_id": age["id"], "draft_id": draft["id"],
                          "published_id": published["id"], "fill_path": f"/survey/{published['id']}",
                          "submissions": stats["total_submissions"], "participants": stats["participant_count"],
                          "age_average": stats["questions"][3]["average"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
