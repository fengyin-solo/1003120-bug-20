"""安全检查台账接口：待办清单与爆破审批链实时同步。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.schemas import ActionResult, EntryPayload
from app.services.inspection import service as inspection_service

router = APIRouter(prefix="/api/inspection", tags=["安全检查台账"])

DEFAULT_ACTOR = "值班管理员"


@router.get("/todos")
def list_todos(
    kind: str | None = Query(default=None, description="blast_check 爆后检查；legacy_review 存量跳级复核"),
) -> dict:
    """读取安全检查待办：数据来自爆破审批链的状态与留痕，不另存一份状态。"""
    todos = inspection_service.list_todos(kind=kind)
    return {
        "total": len(todos),
        "blast_check": sum(1 for todo in todos if todo["kind"] == "blast_check"),
        "legacy_review": sum(1 for todo in todos if todo["kind"] == "legacy_review"),
        "items": todos,
    }


@router.post("/explosive/{entry_id}/review", response_model=ActionResult)
def review_legacy(entry_id: int, payload: EntryPayload) -> ActionResult:
    """复核存量跳级记录：认可当时的人工签字并销账，状态不回改、不补造。"""
    actor = str(payload.values.get("actor") or DEFAULT_ACTOR).strip() or DEFAULT_ACTOR
    opinion = str(payload.values.get("opinion") or payload.remark or "").strip()
    entry, message = inspection_service.review_legacy(entry_id, actor=actor, opinion=opinion)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
