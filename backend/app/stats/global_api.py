"""同一固定版本跨问卷统计；文本分页返回内容，不返回身份或整份答卷。"""
from collections import Counter
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.auth.dependencies import current_user
from app.questions.logic import accessible_question, version_of
from .api import latest_response_groups, number_average


class GlobalOptionCount(BaseModel):
    id: str
    label: str
    count: int
    percentage: float


class NumberFrequency(BaseModel):
    value: int | float
    count: int
    percentage: float


class GlobalQuestionStatistics(BaseModel):
    question_id: str
    version_id: str
    version_number: int
    type: Literal["single", "multiple", "text", "number"]
    title: str
    statistics_basis: Literal["latest_whole_response_per_user_per_survey"] = "latest_whole_response_per_user_per_survey"
    counting_unit: Literal["valid_answer_occurrence"] = "valid_answer_occurrence"
    referenced_survey_count: int
    answered_survey_count: int
    answered_count: int
    options: list[GlobalOptionCount] = Field(default_factory=list)
    average: float | None = None
    average_display: str | None = None
    distribution: list[NumberFrequency] = Field(default_factory=list)
    distribution_total: int = 0
    distribution_offset: int = 0
    distribution_limit: int = 20
    text_answers: list[str] = Field(default_factory=list)
    text_offset: int = 0
    text_limit: int = 20


def percentage(count, total):
    return round(count * 100 / total, 2) if total else 0.0


def mapped_value(item, content, value):
    if content["type"] not in {"single", "multiple"}:
        return value
    mapping = {o["id"]: o.get("source_option_id") for o in item["options"]}
    valid = {o["id"] for o in content["options"]}
    values = [value] if content["type"] == "single" else value
    try:
        result = [mapping[v] for v in values]
        if any(v not in valid for v in result):
            raise KeyError("invalid version option")
    except (KeyError, TypeError):
        raise HTTPException(409, "题目快照的选项关联不一致，暂不能汇总")
    return result[0] if content["type"] == "single" else result


router = APIRouter(prefix="/api/questions", tags=["题目全局统计"])


@router.get("/{question_id}/versions/{version_id}/statistics", response_model=GlobalQuestionStatistics,
            summary="固定版本跨问卷统计（每卷每账号最新整份答卷）")
def global_statistics(question_id: str, version_id: str, request: Request,
                      offset: Annotated[int, Query(ge=0)] = 0,
                      limit: Annotated[int, Query(ge=1, le=100)] = 20, user=Depends(current_user)):
    database = request.app.state.db
    question = accessible_question(database, question_id, user["_id"])
    version = version_of(question, version_id)
    identifier = str(question["_id"])
    content = version["content"]
    query = {"status": {"$in": ["published", "closed"]}, "questions": {"$elemMatch": {
        "source.question_id": identifier, "source.version_id": version_id}}}
    surveys = database.surveys.find(query, {"questions": 1}).sort([("_id", 1)])
    referenced_count = answered_survey_count = answered_count = 0
    counts = Counter()
    text_answers = []
    for survey in surveys:
        referenced_count += 1
        targets = {q["id"]: q for q in survey["questions"] if
                   (q.get("source") or {}).get("question_id") == identifier
                   and (q.get("source") or {}).get("version_id") == version_id}
        has_sample = False
        groups = latest_response_groups(database, survey["_id"])
        if content["type"] == "text":
            # 固定问卷、账号、答卷中出现位置的顺序，未变更数据翻页不重复或遗漏。
            groups = sorted(groups, key=lambda group: str(group["_id"]))
        for group in groups:
            # 先选整份答卷，再提取其中各出现位置；跳过或空答不回填历史。
            for answer in group["latest"]["answers"]:
                item = targets.get(answer["question_id"])
                value = answer["value"]
                if item is None or value is None or value == "" or value == []:
                    continue
                mapped = mapped_value(item, content, value)
                answered_count += 1
                has_sample = True
                if content["type"] == "multiple":
                    counts.update(mapped)
                elif content["type"] in {"single", "number"}:
                    counts[mapped] += 1
                elif content["type"] == "text" and offset < answered_count <= offset + limit:
                    # 只保留当前页；相同内容作为不同有效回答分别展示。
                    text_answers.append(mapped)
        answered_survey_count += int(has_sample)
    result = {"question_id": identifier, "version_id": version_id, "version_number": version["number"],
              "type": content["type"], "title": content["title"],
              "referenced_survey_count": referenced_count, "answered_survey_count": answered_survey_count,
              "answered_count": answered_count, "distribution_offset": offset, "distribution_limit": limit}
    if content["type"] in {"single", "multiple"}:
        result["options"] = [{"id": option["id"], "label": option["label"], "count": counts[option["id"]],
                              "percentage": percentage(counts[option["id"]], answered_count)} for option in content["options"]]
    elif content["type"] == "number":
        values = sorted(counts)
        result["average"] = number_average(counts)
        result["average_display"] = str(result["average"]) if answered_count else "暂无数据"
        result["distribution_total"] = len(values)
        result["distribution"] = [{"value": value, "count": counts[value], "percentage": percentage(counts[value], answered_count)}
                                  for value in values[offset:offset + limit]]
    elif content["type"] == "text":
        result.update(text_answers=text_answers, text_offset=offset, text_limit=limit)
    return result
