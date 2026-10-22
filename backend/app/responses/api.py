"""填写与提交接口；复用auth模块的当前用户依赖。"""
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from pymongo.errors import DuplicateKeyError

from app.auth.dependencies import current_user
from .logic import ResponseInput, evaluate_response


class FillSurveyOut(BaseModel):
    id: str
    title: str
    description: str
    allow_anonymous: bool
    allow_repeat: bool
    deadline: datetime | None
    questions: list[dict]


class ValidationOut(BaseModel):
    valid: bool = True
    is_anonymous: bool
    question_path: list[str]
    answers: list[dict]


class SubmissionOut(BaseModel):
    id: str
    survey_id: str
    is_anonymous: bool
    submitted_at: datetime


def ensure_open(survey: dict, at: datetime | None = None) -> None:
    if survey["status"] != "published":
        raise HTTPException(409, "问卷已关闭，不能填写或提交")
    if survey["deadline"] is not None and survey["deadline"] <= (at or datetime.now(timezone.utc)):
        raise HTTPException(409, "问卷已截止，不能填写或提交")


def filling_survey(database, survey_id: str, user_id: ObjectId) -> dict:
    if not ObjectId.is_valid(survey_id):
        raise HTTPException(404, "问卷未发布或不存在")
    survey = database.surveys.find_one({"_id": ObjectId(survey_id)})
    if survey is None or survey["status"] == "draft":
        raise HTTPException(404, "问卷未发布或不存在")
    ensure_open(survey)
    if not survey["allow_repeat"] and database.responses.find_one({"survey_id": survey["_id"], "user_id": user_id}, {"_id": 1}):
        raise HTTPException(409, "你已提交过此问卷，不允许重复填写")
    return survey


def validate(survey: dict, body: ResponseInput):
    try:
        return evaluate_response(survey, body)
    except ValueError as error:
        raise HTTPException(422, str(error))

router = APIRouter(prefix="/api/fill/surveys", tags=["填写与提交"])


@router.get("/{survey_id}", response_model=FillSurveyOut, summary="登录后读取可填写问卷")
def get_fill_survey(survey_id: str, request: Request, user=Depends(current_user)):
    survey = filling_survey(request.app.state.db, survey_id, user["_id"])
    return {"id": str(survey["_id"]), **{key: survey[key] for key in
            ["title", "description", "allow_anonymous", "allow_repeat", "deadline", "questions"]}}


@router.post("/{survey_id}/validate", response_model=ValidationOut, summary="校验完整答案与路径（不保存）")
def validate_answers(survey_id: str, body: ResponseInput, request: Request, user=Depends(current_user)):
    survey = filling_survey(request.app.state.db, survey_id, user["_id"])
    answers, path, anonymous = validate(survey, body)
    return {"answers": answers, "question_path": path, "is_anonymous": anonymous}


@router.post("/{survey_id}/responses", response_model=SubmissionOut, status_code=201,
             summary="提交完整答卷（每次成功独立保存）")
def submit_response(survey_id: str, body: ResponseInput, request: Request, user=Depends(current_user)):
    database = request.app.state.db
    survey = filling_survey(database, survey_id, user["_id"])
    answers, _, anonymous = validate(survey, body)
    # 校验完成后再次读取，已打开页面不能绕过关闭、截止或重复限制。
    survey = filling_survey(database, survey_id, user["_id"])
    now = datetime.now(timezone.utc)
    ensure_open(survey, now)
    now = now.replace(microsecond=now.microsecond // 1000 * 1000)
    response = {"_id": ObjectId(), "survey_id": survey["_id"], "user_id": user["_id"],
                "is_anonymous": anonymous, "answers": answers, "submitted_at": now,
                "single_submission": not survey["allow_repeat"]}
    try:
        database.responses.insert_one(response)
    except DuplicateKeyError:
        raise HTTPException(409, "你已提交过此问卷，不允许重复填写")
    return {"id": str(response["_id"]), "survey_id": survey_id,
            "is_anonymous": anonymous, "submitted_at": now}
