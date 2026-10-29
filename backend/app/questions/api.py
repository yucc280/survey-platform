"""独立题目与固定版本接口；不覆盖版本、不删除历史。"""
import re
from copy import deepcopy
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth.dependencies import current_user
from .logic import accessible_question, create_reusable_question, make_version, save_changes, summary, version_of
from .schemas import NewQuestion, NewVersion, RestoreVersion
from .schemas import RevisionInput
from app.surveys.logic import save_survey_changes

router = APIRouter(prefix="/api/questions", tags=["独立题目与版本"])


@router.post("", status_code=201, summary="创建自己的可复用题目及v1")
def create_question(body: NewQuestion, request: Request, user=Depends(current_user)):
    return create_reusable_question(request.app.state.db, user["_id"], body.content)


@router.get("", summary="分页查找自己的题目（按各版本题干搜索）")
def list_questions(request: Request, offset: Annotated[int, Query(ge=0)] = 0,
                   limit: Annotated[int, Query(ge=1, le=100)] = 20,
                   scope: Literal["mine"] = "mine",
                   keyword: Annotated[str, Query(max_length=200)] = "", user=Depends(current_user)):
    collection = request.app.state.db.questions
    query = {"owner_id": user["_id"]}
    query["retired"] = {"$ne": True}
    if keyword.strip():
        query["versions"] = {"$elemMatch": {"content.title": {"$regex": re.escape(keyword.strip()), "$options": "i"}}}
    rows = collection.find(query).sort([("created_at", -1), ("_id", -1)]).skip(offset).limit(limit)
    return {"items": [summary(row) for row in rows], "total": collection.count_documents(query),
            "offset": offset, "limit": limit}


@router.post("/{question_id}/temporary", summary="移出我的题目并将唯一自有引用问卷中的题转回临时题")
def make_temporary(question_id: str, body: RevisionInput, request: Request, user=Depends(current_user)):
    database = request.app.state.db
    question = accessible_question(database, question_id, user["_id"], owner_only=True)
    query = {"questions": {"$elemMatch": {"source.question_id": str(question["_id"])}}}
    surveys = list(database.surveys.find(query))
    if len(surveys) > 1:
        raise HTTPException(409, "该题已被多份问卷引用，不能转回临时题，请查看使用情况")
    if surveys and surveys[0]["owner_id"] != user["_id"]:
        raise HTTPException(409, "该题被他人问卷引用，不能转回临时题")
    locked = save_changes(database, question, body.expected_revision, {"retired": True})
    try:
        # 再检查一次，避免检查到保存之间刚完成的新增引用被遗漏。
        current = list(database.surveys.find(query))
        if current != surveys:
            raise HTTPException(409, "引用情况已变化，请刷新后重试")
        if surveys:
            survey = surveys[0]
            questions = deepcopy(survey["questions"])
            for item in questions:
                if (item.get("source") or {}).get("question_id") == str(question["_id"]):
                    item.pop("source", None)
                    for option in item.get("options", []):
                        option.pop("source_option_id", None)
            save_survey_changes(database.surveys, survey, {"questions": questions})
    except HTTPException:
        save_changes(database, locked, locked["revision"], {"retired": False})
        raise
    return {"message": "已移出我的题目，原问卷题目转为临时题，内容和答卷保留"}


@router.get("/{question_id}/usage", summary="查看题目各版本被哪些问卷使用（不含他人草稿）")
def question_usage(question_id: str, request: Request, version_id: str | None = None,
                   offset: Annotated[int, Query(ge=0)] = 0,
                   limit: Annotated[int, Query(ge=1, le=100)] = 20, user=Depends(current_user)):
    database = request.app.state.db
    question = accessible_question(database, question_id, user["_id"])
    reference = {"source.question_id": str(question["_id"])}
    if version_id is not None:
        version_of(question, version_id)
        reference["source.version_id"] = version_id
    query = {"questions": {"$elemMatch": reference}, "$or": [
        {"owner_id": user["_id"]}, {"status": {"$in": ["published", "closed"]}},
    ]}
    # 只读取本页必需的配置字段；返回时再按白名单排除其他题目及答案。
    rows = list(database.surveys.find(query, {"title": 1, "owner_id": 1, "status": 1,
                "questions": 1, "created_at": 1}).sort([("created_at", -1), ("_id", -1)]).skip(offset).limit(limit))
    names = {u["_id"]: u["username"] for u in database.users.find(
        {"_id": {"$in": list({row["owner_id"] for row in rows})}}, {"username": 1})} if rows else {}
    versions = {v["id"]: v["number"] for v in question["versions"]}
    items = []
    for row in rows:
        used = {}
        for item in row["questions"]:
            source = item.get("source") or {}
            if source.get("question_id") == str(question["_id"]) and (
                    version_id is None or source["version_id"] == version_id):
                # 查询期间可能刚产生新版本/新引用，快照中的固定版本号仍可解释。
                used[source["version_id"]] = versions.get(source["version_id"], source["version_number"])
        items.append({"survey_id": str(row["_id"]), "title": row["title"], "status": row["status"],
                      "creator_username": names.get(row["owner_id"]),
                      "versions": [{"version_id": identifier, "version_number": used[identifier]}
                                   for identifier in sorted(used, key=lambda identifier: used[identifier])]})
    return {"question_id": str(question["_id"]), "version_id": version_id,
            "items": items, "total": database.surveys.count_documents(query), "offset": offset, "limit": limit}


@router.get("/{question_id}", summary="查看题目及当前默认版本")
def get_question(question_id: str, request: Request, user=Depends(current_user)):
    return summary(accessible_question(request.app.state.db, question_id, user["_id"]))


@router.get("/{question_id}/versions", summary="分页查看固定版本历史")
def list_versions(question_id: str, request: Request, offset: Annotated[int, Query(ge=0)] = 0,
                  limit: Annotated[int, Query(ge=1, le=100)] = 20, user=Depends(current_user)):
    question = accessible_question(request.app.state.db, question_id, user["_id"])
    versions = sorted(question["versions"], key=lambda v: v["number"], reverse=True)
    return {"items": versions[offset:offset + limit], "total": len(versions), "offset": offset, "limit": limit}


@router.get("/{question_id}/versions/{version_id}", summary="查看指定固定版本")
def get_version(question_id: str, version_id: str, request: Request, user=Depends(current_user)):
    return version_of(accessible_question(request.app.state.db, question_id, user["_id"]), version_id)


@router.post("/{question_id}/versions", status_code=201, summary="基于当前版本保存新版本")
def create_version(question_id: str, body: NewVersion, request: Request, user=Depends(current_user)):
    database = request.app.state.db
    previous = accessible_question(database, question_id, user["_id"], owner_only=True)
    parent = version_of(previous, previous["current_version_id"])
    version = make_version(body.content, previous["max_version"] + 1, parent)
    return summary(save_changes(database, previous, body.expected_revision, {
        "versions": [*previous["versions"], version], "current_version_id": version["id"],
        "max_version": version["number"],
    }))


@router.patch("/{question_id}/current-version", summary="恢复当前版本（仅切换指针）")
def restore_version(question_id: str, body: RestoreVersion, request: Request, user=Depends(current_user)):
    database = request.app.state.db
    previous = accessible_question(database, question_id, user["_id"], owner_only=True)
    version_of(previous, body.version_id)
    return summary(save_changes(database, previous, body.expected_revision, {"current_version_id": body.version_id}))
