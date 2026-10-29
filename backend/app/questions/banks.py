"""个人题库仅组织逻辑题目；移出成员不删除题目或版本。"""
from typing import Annotated

from bson import BSON, ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pymongo import ReturnDocument

from app.auth.dependencies import current_user
from .logic import accessible_question, now, summary
from .schemas import BankName, BankRename, RevisionInput

router = APIRouter(prefix="/api/question-banks", tags=["题库组织"])
MAX_BANK_BYTES = 15 * 1024 * 1024


def owned_bank(database, identifier, user_id):
    if not ObjectId.is_valid(identifier):
        raise HTTPException(404, "题库不存在或无权访问")
    bank = database.question_banks.find_one({"_id": ObjectId(identifier), "owner_id": user_id})
    if bank is None:
        raise HTTPException(404, "题库不存在或无权访问")
    return bank


def bank_summary(bank):
    return {"id": str(bank["_id"]), "owner_id": str(bank["owner_id"]),
            **{key: bank[key] for key in ["name", "revision", "created_at", "updated_at"]},
            "question_count": len(bank["question_ids"])}


def save_bank(database, previous, revision, changes):
    if previous["revision"] != revision:
        raise HTTPException(409, "题库已变化，请刷新后操作")
    changes = {**changes, "revision": revision + 1, "updated_at": now()}
    if len(BSON.encode({**previous, **changes})) > MAX_BANK_BYTES:
        raise HTTPException(422, "题库成员达到存储上限，本次未保存")
    bank = database.question_banks.find_one_and_update(
        {"_id": previous["_id"], "owner_id": previous["owner_id"], "revision": revision},
        {"$set": changes}, return_document=ReturnDocument.AFTER)
    if bank is None:
        raise HTTPException(409, "题库已变化，请刷新后操作")
    return bank_summary(bank)


@router.post("", status_code=201, summary="创建自己的题库")
def create_bank(body: BankName, request: Request, user=Depends(current_user)):
    at = now()
    bank = {"_id": ObjectId(), "owner_id": user["_id"], "name": body.name, "revision": 0,
            "question_ids": [], "created_at": at, "updated_at": at}
    request.app.state.db.question_banks.insert_one(bank)
    return bank_summary(bank)


@router.get("", summary="分页查看自己的题库")
def list_banks(request: Request, offset: Annotated[int, Query(ge=0)] = 0,
               limit: Annotated[int, Query(ge=1, le=100)] = 20, user=Depends(current_user)):
    collection = request.app.state.db.question_banks
    query = {"owner_id": user["_id"]}
    rows = collection.find(query).sort([("created_at", -1), ("_id", -1)]).skip(offset).limit(limit)
    return {"items": [bank_summary(bank) for bank in rows], "total": collection.count_documents(query),
            "offset": offset, "limit": limit}


@router.get("/{bank_id}", summary="查看题库并分页选题（过滤无权访问的成员）")
def get_bank(bank_id: str, request: Request, offset: Annotated[int, Query(ge=0)] = 0,
             limit: Annotated[int, Query(ge=1, le=100)] = 20, user=Depends(current_user)):
    database = request.app.state.db
    if not ObjectId.is_valid(bank_id):
        raise HTTPException(404, "题库不存在")
    bank = database.question_banks.find_one({"_id": ObjectId(bank_id)})
    if bank is None:
        raise HTTPException(404, "题库不存在")
    query = {"_id": {"$in": bank["question_ids"]}, "owner_id": bank["owner_id"]}
    query["retired"] = {"$ne": True}
    rows = database.questions.find(query).sort([("created_at", -1), ("_id", -1)]).skip(offset).limit(limit)
    total = database.questions.count_documents(query)
    return {**bank_summary(bank), "items": [summary(q) for q in rows], "total": total,
            "unavailable_count": len(bank["question_ids"]) - total, "offset": offset, "limit": limit}


@router.patch("/{bank_id}", summary="修改自己题库的名称")
def rename_bank(bank_id: str, body: BankRename, request: Request, user=Depends(current_user)):
    database = request.app.state.db
    bank = owned_bank(database, bank_id, user["_id"])
    return save_bank(database, bank, body.expected_revision, {"name": body.name})


@router.put("/{bank_id}/questions/{question_id}", summary="将可访问的逻辑题目加入自己的题库")
def add_member(bank_id: str, question_id: str, body: RevisionInput, request: Request, user=Depends(current_user)):
    database = request.app.state.db
    bank = owned_bank(database, bank_id, user["_id"])
    question = accessible_question(database, question_id, user["_id"], owner_only=True)
    ids = list(dict.fromkeys([*bank["question_ids"], question["_id"]]))
    return save_bank(database, bank, body.expected_revision, {"question_ids": ids})


@router.delete("/{bank_id}/questions/{question_id}", summary="从题库移出成员（不删除题目）")
def remove_member(bank_id: str, question_id: str, request: Request,
                  expected_revision: Annotated[int, Query(ge=0)], user=Depends(current_user)):
    database = request.app.state.db
    bank = owned_bank(database, bank_id, user["_id"])
    if not ObjectId.is_valid(question_id):
        raise HTTPException(404, "成员题目ID无效")
    # 即使题目已转回临时题，题库所有者仍可清理保存的组织关系。
    ids = [identifier for identifier in bank["question_ids"] if identifier != ObjectId(question_id)]
    return save_bank(database, bank, expected_revision, {"question_ids": ids})


@router.delete("/{bank_id}", summary="删除自己的题库（题目、问卷与答卷保留）")
def delete_bank(bank_id: str, request: Request, expected_revision: Annotated[int, Query(ge=0)], user=Depends(current_user)):
    database = request.app.state.db
    bank = owned_bank(database, bank_id, user["_id"])
    result = database.question_banks.delete_one({"_id": bank["_id"], "owner_id": user["_id"], "revision": expected_revision})
    if result.deleted_count != 1:
        raise HTTPException(409, "题库已变化，请刷新后操作")
    return {"message": "题库已删除，原题目和已有问卷保留"}
