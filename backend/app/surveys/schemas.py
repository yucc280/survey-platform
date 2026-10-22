"""问卷创建、草稿编辑、发布及管理响应模型。"""
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, field_validator, model_validator

from .questions import QuestionInput


class SurveyCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: StrictStr
    description: StrictStr = ""
    allow_anonymous: StrictBool = False
    allow_repeat: StrictBool = False

    @field_validator("title")
    @classmethod
    def valid_title(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 100:
            raise ValueError("标题须为1～100个字符，不能仅为空白")
        return value

    @field_validator("description")
    @classmethod
    def valid_description(cls, value: str) -> str:
        if len(value) > 1000:
            raise ValueError("问卷说明不能超过1000个字符")
        return value

class SurveySummary(BaseModel):
    id: str
    owner_id: str
    title: str
    description: str
    status: str
    allow_anonymous: bool
    allow_repeat: bool
    deadline: datetime | None
    created_at: datetime
    updated_at: datetime

class DraftEdit(SurveyCreate):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{
        "title": "课程学习调查", "description": "问卷草稿示例",
        "allow_anonymous": False, "allow_repeat": False,
        "questions": [
            {"type": "single", "title": "是否学过MongoDB", "required": True,
             "options": [{"label": "是"}, {"label": "否"}], "validation": {}},
            {"type": "multiple", "title": "感兴趣的内容", "required": True,
             "options": [{"label": "数据库设计"}, {"label": "后端开发"}, {"label": "前端开发"}],
             "validation": {"min_choices": 1, "max_choices": 2}},
            {"type": "text", "title": "学习建议", "required": False,
             "validation": {"max_length": 100}},
            {"type": "number", "title": "年龄", "required": True,
             "validation": {"integer_only": True, "min_value": 0, "max_value": 120}},
        ],
    }]})
    questions: list[QuestionInput] = Field(max_length=100)

    @model_validator(mode="after")
    def unique_question_ids(self):
        ids = [question.id for question in self.questions if question.id is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("题目ID不能重复")
        return self

class SurveyDetail(SurveySummary):
    questions: list[dict]

class SurveyList(BaseModel):
    items: list[SurveySummary]
    total: int
    offset: int
    limit: int

class PublishInput(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"deadline": None}]})
    deadline: datetime | None = None

    @field_validator("deadline")
    @classmethod
    def valid_deadline(cls, value):
        if value is not None:
            if value.utcoffset() is None:
                raise ValueError("截止时间必须带时区，例如北京时间末尾+08:00")
            value = value.astimezone(timezone.utc)
            return value.replace(microsecond=value.microsecond // 1000 * 1000)
        return None

class PublishedSurvey(SurveyDetail):
    fill_url: str

class DeadlineEdit(PublishInput):
    # 必须明确传入新时间或null，避免空对象被误解为取消截止。
    deadline: datetime | None
