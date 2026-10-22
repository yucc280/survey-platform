"""问卷所有权检查、稳定ID、规则引用及原子更新辅助函数。"""
from copy import deepcopy
from datetime import datetime, timezone

from bson import ObjectId
from fastapi import HTTPException
from pymongo import ReturnDocument

from .questions import QuestionInput, validate_question_rules


def public_survey(survey: dict) -> dict:
    # 不原地修改数据库文档，对外统一使用字符串 ID。
    return {**{key: value for key, value in survey.items() if key != "_id"},
            "id": str(survey["_id"]), "owner_id": str(survey["owner_id"])}

def owned_survey(surveys, survey_id: str, user_id: ObjectId) -> dict:
    if not ObjectId.is_valid(survey_id):
        raise HTTPException(404, "问卷不存在或无权访问")
    survey = surveys.find_one({"_id": ObjectId(survey_id), "owner_id": user_id})
    if survey is None:
        raise HTTPException(404, "问卷不存在或无权访问")
    return survey

def draft_questions(inputs: list[QuestionInput], previous: list[dict]) -> list[dict]:
    old_questions = {question["id"]: question for question in previous}
    result = []
    for question in inputs:
        old = old_questions.get(question.id) if question.id is not None else None
        if question.id is not None and old is None:
            raise HTTPException(422, "题目ID不属于当前草稿；新增题目请省略id")
        old_option_ids = {option["id"] for option in old.get("options", [])} if old else set()
        options = []
        for option in question.options:
            if option.id is not None and option.id not in old_option_ids:
                raise HTTPException(422, "选项ID不属于当前题目；新增选项请省略id")
            options.append({"id": option.id if option.id is not None else "opt_" + str(ObjectId()),
                            "label": option.label})
        rules = [rule.model_dump(exclude_none=True) for rule in question.jump_rules]
        if "jump_rules" not in question.model_fields_set and old:
            rules = deepcopy(old.get("jump_rules", []))
        result.append({"id": question.id if question.id is not None else "q_" + str(ObjectId()),
                       "type": question.type, "title": question.title, "required": question.required,
                       "options": options, "validation": question.validation, "jump_rules": rules})
    try:
        validate_question_rules(result)
    except ValueError as error:
        raise HTTPException(422, str(error))
    return result

def save_survey_changes(surveys, previous: dict, changes: dict, extra_filter: dict | None = None) -> dict:
    updated_at = datetime.now(timezone.utc)
    changes["updated_at"] = updated_at.replace(microsecond=updated_at.microsecond // 1000 * 1000)
    query = {**previous, **(extra_filter or {})}
    saved = surveys.find_one_and_update(query, {"$set": changes}, return_document=ReturnDocument.AFTER)
    if saved is None:
        raise HTTPException(409, "问卷状态或内容已变化，请重新读取后操作")
    return saved
