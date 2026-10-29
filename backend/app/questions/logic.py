"""独立题目和固定版本；历史嵌入单文档，通过修订号防止并发覆盖。"""
from copy import deepcopy
from datetime import datetime, timezone

from bson import BSON, ObjectId
from fastapi import HTTPException
from pymongo import ReturnDocument

MAX_QUESTION_BYTES = 15 * 1024 * 1024


def now():
    value = datetime.now(timezone.utc)
    return value.replace(microsecond=value.microsecond // 1000 * 1000)


def accessible_question(database, identifier, user_id, *, owner_only=False, for_reuse=False):
    if not ObjectId.is_valid(identifier):
        raise HTTPException(404, "题目不存在或无权访问")
    question = database.questions.find_one({"_id": ObjectId(identifier)})
    if question is None or question.get("retired", False):
        raise HTTPException(404, "题目不存在或无权访问")
    if question["owner_id"] != user_id:
        shared = database.question_banks.count_documents({"owner_id": question["owner_id"], "question_ids": question["_id"]}) > 0
        if owner_only or (for_reuse and not shared):
            raise HTTPException(404, "题目不存在或无权访问")
        if not shared:
            rows = database.surveys.find({"owner_id": user_id, "questions": {"$elemMatch": {"source.question_id": str(question["_id"])}}})
            used = {item["source"]["version_id"] for row in rows for item in row["questions"]
                    if (item.get("source") or {}).get("question_id") == str(question["_id"])}
            if not used:
                raise HTTPException(404, "题目不存在或无权访问")
            question = deepcopy(question)
            question["versions"] = [v for v in question["versions"] if v["id"] in used]
            latest = max(question["versions"], key=lambda v: v["number"])
            question["current_version_id"] = latest["id"]
            question["max_version"] = latest["number"]
    return question


def version_of(question, identifier):
    version = next((v for v in question["versions"] if v["id"] == identifier), None)
    if version is None:
        raise HTTPException(404, "版本不属于该题目或不存在")
    return version


def make_version(content, number, parent=None):
    data = content.model_dump()
    old_ids = {o["id"] for o in parent["content"]["options"]} if parent else set()
    for option in data["options"]:
        if option["id"] is not None and option["id"] not in old_ids:
            raise HTTPException(422, "选项ID必须属于当前版本；新选项请省略id")
        option["id"] = option["id"] or "vo_" + str(ObjectId())
    return {"id": "v_" + str(ObjectId()), "number": number,
            "parent_version_id": parent["id"] if parent else None,
            "content": data, "created_at": now()}


def summary(question):
    return {"id": str(question["_id"]), "owner_id": str(question["owner_id"]),
            **{key: question[key] for key in ["current_version_id", "max_version", "revision", "created_at", "updated_at"]},
            "current_version": version_of(question, question["current_version_id"])}


def check_size(question):
    try:
        size = len(BSON.encode(question))
    except OverflowError:
        raise HTTPException(422, "配置整数超出数据库可保存的范围，本次未保存")
    if size > MAX_QUESTION_BYTES:
        raise HTTPException(422, "题目历史已达到存储上限，本次未保存，原有版本保持不变")


def create_reusable_question(database, owner_id, content):
    """手工新建和从问卷保存共用同一v1创建过程。"""
    version = make_version(content, 1)
    at = now()
    question = {"_id": ObjectId(), "owner_id": owner_id,
                "current_version_id": version["id"], "max_version": 1, "revision": 0,
                "versions": [version], "created_at": at, "updated_at": at}
    check_size(question)
    database.questions.insert_one(question)
    return summary(question)


def save_changes(database, previous, revision, changes):
    if previous["revision"] != revision:
        raise HTTPException(409, "题目已变化，请刷新后再操作")
    changes = {**changes, "revision": revision + 1, "updated_at": now()}
    check_size({**previous, **changes})
    saved = database.questions.find_one_and_update(
        {"_id": previous["_id"], "owner_id": previous["owner_id"], "revision": revision},
        {"$set": changes}, return_document=ReturnDocument.AFTER,
    )
    if saved is None:
        raise HTTPException(409, "题目已变化，请刷新后再操作")
    return saved


def snapshot(version, reference, *, previous=None):
    """问卷内部ID保持独立；新版本选项映射由服务端建立。"""
    data = deepcopy(version["content"])
    for option in data["options"]:
        option["source_option_id"] = option["id"]
        option["id"] = "opt_" + str(ObjectId())
    return {**data, "id": previous["id"] if previous else "q_" + str(ObjectId()),
            "required": previous["required"] if previous else False,
            "jump_rules": deepcopy(previous["jump_rules"]) if previous else [],
            "source": {"question_id": reference.question_id.lower(), "version_id": reference.version_id,
                       "version_number": version["number"]}}
