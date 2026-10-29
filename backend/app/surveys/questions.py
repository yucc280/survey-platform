"""草稿题目配置校验；这是创建者配置的校验，不是填写者答案校验。"""
import math
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, field_validator, model_validator


class ValidationBase(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class MultipleValidation(ValidationBase):
    min_choices: StrictInt | None = Field(default=None, ge=0)
    max_choices: StrictInt | None = Field(default=None, ge=0)


class TextValidation(ValidationBase):
    min_length: StrictInt | None = Field(default=None, ge=0)
    max_length: StrictInt | None = Field(default=None, ge=0)


class NumberValidation(ValidationBase):
    min_value: StrictInt | StrictFloat | None = None
    max_value: StrictInt | StrictFloat | None = None
    integer_only: StrictBool = False
    phone_format: StrictBool = False


class OptionInput(ValidationBase):
    id: StrictStr | None = None
    source_option_id: StrictStr | None = None
    label: StrictStr

    @field_validator("label")
    @classmethod
    def valid_label(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 100:
            raise ValueError("选项文字须为1～100个字符，不能仅为空白")
        return value


class JumpCondition(ValidationBase):
    operator: Literal["equals", "contains", "contains_all", "gt", "gte", "lt", "lte", "eq"]
    value: StrictStr | list[StrictStr] | StrictInt | StrictFloat


class JumpTarget(ValidationBase):
    kind: Literal["question", "end"]
    question_id: StrictStr | None = None

    @model_validator(mode="after")
    def valid_target(self):
        if self.kind == "question" and not self.question_id:
            raise ValueError("跳转到题目时必须提供question_id")
        if self.kind == "end" and self.question_id is not None:
            raise ValueError("结束目标不能带question_id")
        return self


class JumpRule(ValidationBase):
    condition: JumpCondition
    target: JumpTarget


class JumpRulesEdit(ValidationBase):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"jump_rules": [{
        "condition": {"operator": "equals", "value": "替换为该单选题的选项ID"},
        "target": {"kind": "end"},
    }]}]})
    jump_rules: list[JumpRule]


class QuestionSource(ValidationBase):
    question_id: StrictStr
    version_id: StrictStr
    version_number: StrictInt = Field(ge=1)


class QuestionInput(ValidationBase):
    id: StrictStr | None = None
    type: Literal["single", "multiple", "text", "number"]
    title: StrictStr
    required: StrictBool = False
    options: list[OptionInput] = Field(default_factory=list, max_length=30)
    validation: dict[str, Any] = Field(default_factory=dict)
    jump_rules: list[JumpRule] = Field(default_factory=list)
    source: QuestionSource | None = None

    @field_validator("title")
    @classmethod
    def valid_title(cls, value: str) -> str:
        value = value.strip()
        if not 1 <= len(value) <= 200:
            raise ValueError("题干须为1～200个字符，不能仅为空白")
        return value

    @model_validator(mode="after")
    def valid_configuration(self):
        choice = self.type in {"single", "multiple"}
        if choice and len(self.options) < 2:
            raise ValueError("选择题须有2～30个选项")
        if not choice and self.options:
            raise ValueError("填空题不能配置选项")
        ids = [option.id for option in self.options if option.id is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("同一道题中选项ID不能重复")
        validation_type = {"single": ValidationBase, "multiple": MultipleValidation,
                           "text": TextValidation, "number": NumberValidation}[self.type]
        config = validation_type.model_validate(self.validation).model_dump(exclude_none=True)
        names = {"multiple": ("min_choices", "max_choices"), "text": ("min_length", "max_length"),
                 "number": ("min_value", "max_value")}
        if self.type in names:
            lower_name, upper_name = names[self.type]
            lower, upper = config.get(lower_name), config.get(upper_name)
            if lower is not None and upper is not None and lower > upper:
                raise ValueError("校验最小值不能大于最大值")
            if self.required and self.type in {"multiple", "text"} and upper == 0:
                raise ValueError("必答题的最大选择数或最大字符数不能为0")
            if self.type == "multiple" and any(
                value is not None and value > len(self.options) for value in [lower, upper]
            ):
                raise ValueError("选择数量限制不能超过选项总数")
            if self.type == "number":
                if config["phone_format"] and not config["integer_only"]:
                    raise ValueError("手机号格式校验必须同时启用整数要求")
                if config["integer_only"] and lower is not None and upper is not None:
                    if math.ceil(lower) > math.floor(upper):
                        raise ValueError("该范围内没有可填写的整数")
        self.validation = config
        return self


def validate_question_rules(questions: list[dict]) -> None:
    """检查题目间引用；失败时不允许保存整个更新。"""
    ids = [question.get("id") for question in questions]
    if any(not isinstance(identifier, str) or not identifier for identifier in ids) or len(set(ids)) != len(ids):
        raise ValueError("所有题目必须具有唯一且非空的稳定ID")
    positions = {identifier: index for index, identifier in enumerate(ids)}
    for index, question in enumerate(questions):
        option_ids = [option.get("id") for option in question.get("options", [])]
        if any(not isinstance(identifier, str) or not identifier for identifier in option_ids) or len(set(option_ids)) != len(option_ids):
            raise ValueError("选项必须具有当前题目内唯一且非空的ID")
        for raw_rule in question.get("jump_rules", []):
            rule = JumpRule.model_validate(raw_rule)
            operator, value = rule.condition.operator, rule.condition.value
            if question["type"] == "single":
                valid = operator == "equals" and isinstance(value, str) and value in option_ids
            elif question["type"] == "multiple":
                valid = (operator == "contains" and isinstance(value, str) and value in option_ids) or (
                    operator == "contains_all" and isinstance(value, list) and bool(value)
                    and len(value) == len(set(value)) and all(item in option_ids for item in value)
                )
            elif question["type"] == "number":
                valid = operator in {"gt", "gte", "lt", "lte", "eq"} and type(value) in {int, float}
            else:
                valid = False
            if not valid:
                raise ValueError(f"题目 {question['id']} 的跳转条件与题型或选项不匹配")
            target = rule.target
            if target.kind == "question" and (
                target.question_id not in positions or positions[target.question_id] <= index
            ):
                raise ValueError("跳转目标必须是本问卷中位于来源题之后的题目")
