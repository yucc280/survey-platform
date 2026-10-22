"""创建者问卷配置与发布生命周期接口。"""
from copy import deepcopy
from datetime import datetime, timezone
from typing import Annotated

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
from pymongo import DESCENDING

from app.auth.dependencies import current_user
from app.database import get_surveys
from .logic import draft_questions, owned_survey, public_survey, save_survey_changes
from .questions import JumpRulesEdit, validate_question_rules
from .schemas import DeadlineEdit, DraftEdit, PublishedSurvey, PublishInput, SurveyCreate, SurveyDetail, SurveyList

router = APIRouter()


@router.post("/api/surveys", response_model=SurveyDetail, status_code=201,
                  summary="创建问卷草稿", tags=["问卷管理"],
                  responses={401: {"description": "未登录或令牌失效"}})
def create_survey(body: SurveyCreate, user=Depends(current_user), surveys=Depends(get_surveys)):
    now = datetime.now(timezone.utc)
    # BSON 日期精度为毫秒，统一首次响应与之后读回的时间精度。
    now = now.replace(microsecond=now.microsecond // 1000 * 1000)
    survey = {
        "_id": ObjectId(), "owner_id": user["_id"], **body.model_dump(),
        "status": "draft", "deadline": None, "questions": [],
        "created_at": now, "updated_at": now,
    }
    surveys.insert_one(survey)
    return public_survey(survey)

@router.get("/api/surveys", response_model=SurveyList,
                 summary="查看自己的问卷列表", tags=["问卷管理"],
                 responses={401: {"description": "未登录或令牌失效"}})
def list_surveys(
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    user=Depends(current_user), surveys=Depends(get_surveys),
):
    query = {"owner_id": user["_id"]}
    rows = surveys.find(query, {"questions": 0}).sort(
        [("created_at", DESCENDING), ("_id", DESCENDING)]
    ).skip(offset).limit(limit)
    return {"items": [public_survey(row) for row in rows],
            "total": surveys.count_documents(query), "offset": offset, "limit": limit}

@router.get("/api/surveys/{survey_id}", response_model=SurveyDetail,
                 summary="查看自己问卷的管理详情", tags=["问卷管理"],
                 responses={401: {"description": "未登录或令牌失效"},
                            404: {"description": "问卷不存在或不属于当前用户"}})
def get_survey(survey_id: str, user=Depends(current_user), surveys=Depends(get_surveys)):
    # ID 非法也返回404；同时按创建者过滤，不暴露他人的问卷是否存在。
    survey = owned_survey(surveys, survey_id, user["_id"])
    return public_survey(survey)

@router.delete("/api/surveys/{survey_id}", summary="永久删除自己的问卷草稿", tags=["问卷管理"],
               responses={401: {"description": "未登录"}, 404: {"description": "问卷不存在或非本人"},
                          409: {"description": "非草稿或问卷已变化"}})
def delete_survey(survey_id: str, user=Depends(current_user), surveys=Depends(get_surveys)):
    previous = owned_survey(surveys, survey_id, user["_id"])
    if previous["status"] != "draft":
        raise HTTPException(409, "当前尚不支持该状态下的问卷删除")
    # 原文档条件包含所有者和draft状态；读取后发布或修改均不能被误删。
    result = surveys.delete_one(previous)
    if result.deleted_count != 1:
        raise HTTPException(409, "问卷状态或内容已变化，请刷新列表后重试")
    return {"message": "问卷草稿已删除"}


@router.put("/api/surveys/{survey_id}", response_model=SurveyDetail,
                 summary="保存完整问卷草稿（替换编辑内容）", tags=["问卷管理"],
                 responses={401: {"description": "未登录或令牌失效"},
                            404: {"description": "问卷不存在或不属于当前用户"},
                            409: {"description": "已发布、已关闭或编辑期间内容变化"}})
def edit_survey(survey_id: str, body: DraftEdit, user=Depends(current_user), surveys=Depends(get_surveys)):
    previous = owned_survey(surveys, survey_id, user["_id"])
    if previous["status"] != "draft":
        raise HTTPException(409, "只有草稿可以编辑")
    changes = body.model_dump(exclude={"questions"})
    changes["questions"] = draft_questions(body.questions, previous["questions"])
    # 单次原子更新同时匹配原始内容与draft状态，避免读后发布或并发修改被覆盖。
    saved = save_survey_changes(surveys, previous, changes)
    return public_survey(saved)

@router.put("/api/surveys/{survey_id}/questions/{question_id}/jump-rules",
                 response_model=SurveyDetail, summary="配置某道题的有序跳转规则", tags=["问卷管理"])
def edit_jump_rules(survey_id: str, question_id: str, body: JumpRulesEdit,
                    user=Depends(current_user), surveys=Depends(get_surveys)):
    previous = owned_survey(surveys, survey_id, user["_id"])
    if previous["status"] != "draft":
        raise HTTPException(409, "只有草稿可以编辑跳转规则")
    questions = deepcopy(previous["questions"])
    question = next((item for item in questions if item["id"] == question_id), None)
    if question is None:
        raise HTTPException(404, "题目不存在")
    question["jump_rules"] = [rule.model_dump(exclude_none=True) for rule in body.jump_rules]
    try:
        validate_question_rules(questions)
    except ValueError as error:
        raise HTTPException(422, str(error))
    return public_survey(save_survey_changes(surveys, previous, {"questions": questions}))

@router.post("/api/surveys/{survey_id}/publish", response_model=PublishedSurvey,
                  summary="校验并发布问卷", tags=["问卷管理"])
def publish_survey(survey_id: str, body: PublishInput,
                   user=Depends(current_user), surveys=Depends(get_surveys)):
    previous = owned_survey(surveys, survey_id, user["_id"])
    if previous["status"] != "draft":
        raise HTTPException(409, "只有草稿可以发布")
    if not previous["questions"]:
        raise HTTPException(422, "发布前至少需要一道题目")
    try:
        DraftEdit.model_validate({key: previous[key] for key in
                                 ["title", "description", "allow_anonymous", "allow_repeat", "questions"]})
        validate_question_rules(previous["questions"])
    except (ValueError, ValidationError) as error:
        raise HTTPException(422, "问卷配置不完整或不合法：" + str(error))
    if body.deadline is not None and body.deadline <= datetime.now(timezone.utc):
        raise HTTPException(422, "截止时间必须晚于当前时间")
    saved = save_survey_changes(surveys, previous, {"status": "published", "deadline": body.deadline})
    return {**public_survey(saved), "fill_url": f"/survey/{survey_id}"}

@router.patch("/api/surveys/{survey_id}/deadline", response_model=SurveyDetail,
                   summary="截止前调整已发布问卷的截止时间", tags=["问卷管理"])
def change_deadline(survey_id: str, body: DeadlineEdit,
                    user=Depends(current_user), surveys=Depends(get_surveys)):
    previous = owned_survey(surveys, survey_id, user["_id"])
    if previous["status"] != "published":
        raise HTTPException(409, "只有未关闭的已发布问卷可以调整截止时间")
    now = datetime.now(timezone.utc)
    if previous["deadline"] is not None and previous["deadline"] <= now:
        raise HTTPException(409, "问卷已到期，不能恢复开放")
    if body.deadline is not None and body.deadline <= now:
        raise HTTPException(422, "新的截止时间必须晚于当前时间")
    # 在数据库真正执行更新时再次检查旧截止，防止跨过截止后才写入。
    open_filter = {"$expr": {"$or": [
        {"$eq": ["$deadline", None]}, {"$gt": ["$deadline", "$$NOW"]},
    ]}}
    saved = save_survey_changes(surveys, previous, {"deadline": body.deadline}, open_filter)
    return public_survey(saved)

@router.post("/api/surveys/{survey_id}/close", response_model=SurveyDetail,
                  summary="手动关闭已发布问卷", tags=["问卷管理"])
def close_survey(survey_id: str, user=Depends(current_user), surveys=Depends(get_surveys)):
    previous = owned_survey(surveys, survey_id, user["_id"])
    if previous["status"] != "published":
        raise HTTPException(409, "只有已发布问卷可以关闭")
    return public_survey(save_survey_changes(surveys, previous, {"status": "closed"}))
