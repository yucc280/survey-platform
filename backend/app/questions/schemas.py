"""可复用题目不包含必答或跳转；复用原问卷四题型配置校验。"""
from typing import Any, Literal

from pydantic import ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator

from app.surveys.questions import QuestionInput, ValidationBase


class VersionOption(ValidationBase):
    id: StrictStr | None = None
    label: StrictStr


class QuestionContent(ValidationBase):
    type: Literal["single", "multiple", "text", "number"]
    title: StrictStr
    options: list[VersionOption] = Field(default_factory=list, max_length=30)
    validation: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_content(self):
        checked = QuestionInput.model_validate(self.model_dump())
        self.title = checked.title
        self.options = [VersionOption(id=o.id, label=o.label) for o in checked.options]
        self.validation = checked.validation
        return self


class NewQuestion(ValidationBase):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"content": {
        "type": "number", "title": "你的年龄", "options": [],
        "validation": {"integer_only": True, "min_value": 0, "max_value": 120},
    }}]})
    content: QuestionContent


class RevisionInput(ValidationBase):
    expected_revision: StrictInt = Field(ge=0)


class NewVersion(RevisionInput):
    content: QuestionContent


class RestoreVersion(RevisionInput):
    version_id: StrictStr


class QuestionReference(ValidationBase):
    question_id: StrictStr
    version_id: StrictStr


class BankName(ValidationBase):
    name: StrictStr

    @field_validator("name")
    @classmethod
    def valid_name(cls, value):
        value = value.strip()
        if not 1 <= len(value) <= 100:
            raise ValueError("题库名称须为1～100个字符，不能仅为空白")
        return value


class BankRename(BankName, RevisionInput):
    pass
