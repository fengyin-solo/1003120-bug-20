"""爆破管理接口：维护爆破记录，覆盖提交审批、安全确认、执行爆破、爆后检查与留痕查询。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.explosive import DEFAULT_ACTOR, ExplosiveService

router = APIRouter(prefix="/api/explosive", tags=["爆破管理"])

service = ExplosiveService()

LIST_FIELDS = ["爆破编号", "爆破区域", "炸药用量", "雷管用量", "爆破时间", "警戒范围", "爆破人员"]
STATUSES = ["待审批", "已审批", "已爆破", "已检查"]


def _actor(payload: EntryPayload) -> str:
    return str(payload.values.get("actor") or DEFAULT_ACTOR).strip() or DEFAULT_ACTOR


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按爆破编号检索"),
    status: str | None = Query(default=None, description="待审批、已审批、已爆破、已检查"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按爆破编号与状态过滤爆破管理列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出爆破管理清单：返回当前过滤条件下的全量数据（含审批链留痕）。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "explosive", "total": total, "items": items}


@router.get("/{entry_id}/history")
def entry_history(entry_id: int) -> dict[str, Any]:
    """读取单条爆破记录的状态变更留痕：谁、什么时刻、把记录从哪一步推到哪一步。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"爆破记录 {entry_id} 不存在或已归档")
    return {
        "entry_id": entry_id,
        "爆破编号": entry.get("爆破编号"),
        "status": entry.get("status"),
        "legacy_skipped": bool(entry.get("legacy_skipped")),
        "legacy_reviewed": bool(entry.get("legacy_reviewed")),
        "history": entry.get("history", []),
    }


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条爆破记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"爆破记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条爆破记录，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values, actor=_actor(payload))
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="爆破记录已登记，进入待审批", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条爆破记录执行提交审批、执行爆破、爆后检查。

    跳级、倒序回退、缺审批结论、缺安全确认以及重复提交都会被拦下，message 写明原因。
    """
    action = str(payload.values.get("action") or "").strip()
    conclusion = str(payload.values.get("conclusion") or "").strip()
    entry, message, changed = service.run_action(
        entry_id,
        action,
        actor=_actor(payload),
        conclusion=conclusion,
        remark=payload.remark or "",
    )
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=changed, message=message, entry=entry)


@router.post("/{entry_id}/safety-confirm", response_model=ActionResult)
def confirm_safety(entry_id: int, payload: EntryPayload) -> ActionResult:
    """安全确认：审批通过、爆破之前必须完成的签字环节，只留痕不改审批状态。"""
    entry, message = service.confirm_safety(
        entry_id, actor=_actor(payload), remark=payload.remark or ""
    )
    if entry is None:
        return ActionResult(ok=False, message=message)
    already = "只确认一次" in message
    return ActionResult(ok=not already, message=message, entry=entry)
