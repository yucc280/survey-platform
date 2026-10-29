"""创建者统计：MongoDB按账号选最新整份答卷，再计算各题结果。"""
from decimal import Decimal
from collections import Counter
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth.dependencies import current_user
from app.surveys.logic import owned_survey


class OptionCount(BaseModel):
    id: str
    label: str
    count: int


class QuestionStatistics(BaseModel):
    question_id: str
    type: str
    title: str
    answered_count: int
    options: list[OptionCount] = Field(default_factory=list)
    values: list[str | int | float] = Field(default_factory=list)
    average: float | None = None
    average_display: str | None = None


class PublicAnswer(BaseModel):
    question_id: str
    value: str | list[str] | int | float | None


class PublicLatestResponse(BaseModel):
    is_anonymous: bool
    username: str | None
    answers: list[PublicAnswer]


class SurveyStatistics(BaseModel):
    survey_id: str
    title: str
    total_submissions: int
    participant_count: int
    statistics_basis: Literal["latest_response_per_user"] = "latest_response_per_user"
    questions: list[QuestionStatistics]
    latest_responses: list[PublicLatestResponse]


class SingleQuestionStatistics(BaseModel):
    survey_id: str
    total_submissions: int
    participant_count: int
    statistics_basis: Literal["latest_response_per_user"] = "latest_response_per_user"
    question: QuestionStatistics
    latest_responses: list[PublicLatestResponse]


def latest_response_groups(database, survey_id):
    """每账号最新整份答卷；不查询用户名，供本卷与全局统计共用。"""
    return database.responses.aggregate([
        {"$match": {"survey_id": survey_id}},
        {"$sort": {"user_id": 1, "submitted_at": -1, "_id": -1}},
        {"$group": {"_id": "$user_id", "latest": {"$first": "$$ROOT"}, "submission_count": {"$sum": 1}}},
    ])


def number_average(counts):
    """按数值频次计算均值，避免有限大数直接相加溢出。"""
    count = sum(counts.values())
    return float(sum((Decimal(str(value)) * times for value, times in counts.items()), Decimal(0)) / count) if count else None


def latest_samples(database, survey_id):
    groups = list(latest_response_groups(database, survey_id))
    total = sum(group["submission_count"] for group in groups)
    latest = sorted((group["latest"] for group in groups),
                    key=lambda row: (row["submitted_at"], row["_id"]), reverse=True)
    # 只查询最新实名答卷所需用户名；匿名账号不加入查询集合。
    named_ids = list({row["user_id"] for row in latest if not row["is_anonymous"]})
    names = {user["_id"]: user["username"] for user in database.users.find(
        {"_id": {"$in": named_ids}}, {"username": 1}
    )} if named_ids else {}
    return total, latest, names


def question_statistics(question: dict, latest: list[dict]) -> dict:
    identifier = question["id"]
    values = []
    for row in latest:
        value = next((answer["value"] for answer in row["answers"] if answer["question_id"] == identifier), None)
        if value is not None and value != "" and value != []:
            values.append(value)
    result = {"question_id": identifier, "type": question["type"],
              "title": question["title"], "answered_count": len(values)}
    if question["type"] in {"single", "multiple"}:
        result["options"] = [
            {"id": option["id"], "label": option["label"],
             "count": sum(value == option["id"] if question["type"] == "single" else option["id"] in value
                          for value in values)}
            for option in question["options"]
        ]
    else:
        result["values"] = values
        if question["type"] == "number":
            # Decimal累加避免两个很大的有限浮点数相加变成Infinity。
            average = number_average(Counter(values))
            result["average"] = average
            result["average_display"] = str(average) if average is not None else "暂无数据"
    return result


def visible_responses(latest: list[dict], names: dict, question_id: str | None = None) -> list[dict]:
    return [
        {"is_anonymous": row["is_anonymous"],
         "username": None if row["is_anonymous"] else names.get(row["user_id"]),
         "answers": [{"question_id": answer["question_id"], "value": answer["value"]}
                     for answer in row["answers"] if question_id is None or answer["question_id"] == question_id]}
        for row in latest
    ]

router = APIRouter(prefix="/api/surveys", tags=["结果统计"])


@router.get("/{survey_id}/statistics", response_model=SurveyStatistics, summary="创建者查看整份问卷统计")
def survey_statistics(survey_id: str, request: Request, user=Depends(current_user)):
    database = request.app.state.db
    survey = owned_survey(database.surveys, survey_id, user["_id"])
    total, latest, names = latest_samples(database, survey["_id"])
    return {"survey_id": survey_id, "title": survey["title"], "total_submissions": total,
            "participant_count": len(latest), "latest_responses": visible_responses(latest, names),
            "questions": [question_statistics(question, latest) for question in survey["questions"]]}


@router.get("/{survey_id}/questions/{question_id}/statistics", response_model=SingleQuestionStatistics,
            summary="创建者查看某一道题统计")
def one_question_statistics(survey_id: str, question_id: str, request: Request, user=Depends(current_user)):
    database = request.app.state.db
    survey = owned_survey(database.surveys, survey_id, user["_id"])
    question = next((item for item in survey["questions"] if item["id"] == question_id), None)
    if question is None:
        raise HTTPException(404, "题目不存在")
    total, latest, names = latest_samples(database, survey["_id"])
    return {"survey_id": survey_id, "total_submissions": total, "participant_count": len(latest),
            "question": question_statistics(question, latest),
            "latest_responses": visible_responses(latest, names, question_id)}
