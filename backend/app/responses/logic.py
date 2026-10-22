"""填写答案校验与有效路径计算；不访问数据库，便于独立测试。"""
import math
import re
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, model_validator

from app.surveys.jumps import first_jump_target


class AnswerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    question_id: StrictStr
    value: StrictStr | list[StrictStr] | StrictInt | StrictFloat | None = None


class ResponseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{
        "is_anonymous": False,
        "answers": [{"question_id": "替换为题目ID", "value": "替换为选项ID或填写内容"}],
    }]})
    is_anonymous: StrictBool | None = None
    answers: list[AnswerInput] = Field(max_length=100)

    @model_validator(mode="after")
    def unique_answers(self):
        ids = [answer.question_id for answer in self.answers]
        if len(ids) != len(set(ids)):
            raise ValueError("同一道题只能提交一个答案")
        return self


def normalized_answer(question: dict, value):
    kind = question["type"]
    empty = value is None or value == "" or (kind == "multiple" and value == []) or (
        kind == "text" and isinstance(value, str) and not value.strip()
    )
    if empty:
        if question["required"]:
            raise ValueError("必答题不能为空")
        return None
    config = question.get("validation", {})
    option_ids = {option["id"] for option in question.get("options", [])}
    if kind == "single":
        if not isinstance(value, str) or value not in option_ids:
            raise ValueError("请选择该题的一个有效选项")
        return value
    if kind == "multiple":
        if not isinstance(value, list) or len(value) != len(set(value)) or any(item not in option_ids for item in value):
            raise ValueError("多选答案必须是无重复的有效选项ID数组")
        if len(value) < config.get("min_choices", 0) or len(value) > config.get("max_choices", len(option_ids)):
            raise ValueError("选择数量不符合要求")
        return value
    if kind == "text":
        if not isinstance(value, str):
            raise ValueError("文本题必须填写文字")
        value = value.strip()
        if len(value) < config.get("min_length", 0) or ("max_length" in config and len(value) > config["max_length"]):
            raise ValueError("文字长度不符合要求")
        return value
    if kind != "number":
        raise ValueError("不支持的题型")
    if config.get("phone_format"):
        # 手机号先校验原始格式，不能把小数、科学计数法或空格转换后当作合法号码。
        if type(value) not in {str, int} or not re.fullmatch(r"1[3-9][0-9]{9}", str(value)):
            raise ValueError("手机号须为11位数字，首位1、第二位3～9，不带国家码或分隔符")
        number = int(value)
    else:
        if isinstance(value, str):
            text = value.strip()
            if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", text):
                raise ValueError("请填写普通十进制数字")
            decimal = Decimal(text)
            if config.get("integer_only") and decimal != decimal.to_integral_value():
                raise ValueError("该题必须填写整数")
            number = int(decimal) if decimal == decimal.to_integral_value() else float(decimal)
        elif type(value) in {int, float}:
            number = value
        else:
            raise ValueError("请填写数字")
        if isinstance(number, float) and not math.isfinite(number):
            raise ValueError("数字必须是有限值")
        if config.get("integer_only"):
            if isinstance(number, float) and not number.is_integer():
                raise ValueError("该题必须填写整数")
            number = int(number)
    if type(number) is int and not -(2 ** 63) <= number < 2 ** 63:
        raise ValueError("整数超出数据库可保存的范围")
    if "min_value" in config and number < config["min_value"]:
        raise ValueError("数字小于允许的最小值")
    if "max_value" in config and number > config["max_value"]:
        raise ValueError("数字大于允许的最大值")
    return number


def evaluate_response(survey: dict, body: ResponseInput) -> tuple[list[dict], list[str], bool]:
    anonymous = survey["allow_anonymous"] if body.is_anonymous is None else body.is_anonymous
    if anonymous and not survey["allow_anonymous"]:
        raise ValueError("此问卷不允许匿名提交")
    questions = survey["questions"]
    positions = {question["id"]: index for index, question in enumerate(questions)}
    provided = {answer.question_id: answer.value for answer in body.answers}
    if any(identifier not in positions for identifier in provided):
        raise ValueError("包含不属于该问卷的题目ID")
    answers, path = [], []
    index = 0
    while index < len(questions):
        question = questions[index]
        identifier = question["id"]
        try:
            value = normalized_answer(question, provided.get(identifier))
        except ValueError as error:
            raise ValueError(f"题目 {identifier}（{question['title']}）：{error}") from error
        answers.append({"question_id": identifier, "value": value})
        path.append(identifier)
        target = first_jump_target(question, value)
        if target is None:
            index += 1
        elif target["kind"] == "end":
            break
        else:
            next_index = positions.get(target["question_id"], -1)
            if next_index <= index:
                raise ValueError("问卷跳转配置无效，请联系创建者")
            index = next_index
    if set(provided) - set(path):
        raise ValueError("包含当前答题路径之外的答案，请清除跳过题目的旧答案")
    return answers, path, anonymous
