"""安全检查台账接口：列出爆破链上的安全确认待办，并受理存量跳级记录的人工复核。"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.safety_ledger import SafetyLedgerService

router = APIRouter(prefix="/api/safety-ledger", tags=["安全检查台账"])

service = SafetyLedgerService()


@router.get("", response_model=PageResult[dict])
def list_todos(
    status: str | None = Query(default=None, description="待检查、待复核、已核销；默认只看未办"),
    kind: str | None = Query(default=None, description="爆后安全检查、存量跳级复核"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """安全检查台账待办清单；默认只返回未核销项，已核销项显式传 status 查看。"""
    if size > 200:
        return PageResult(items=[], total=0, page=page, size=size)
    items, total = service.list_todos(status=status, kind=kind, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/{todo_id}/review", response_model=ActionResult)
def review_todo(todo_id: int, payload: EntryPayload) -> ActionResult:
    """对存量跳级挂账登记人工复核结论；没有结论不予核销。"""
    values = payload.values
    result = str(values.get("result") or values.get("remark") or "").strip()
    operator = str(values.get("operator") or "值班管理员").strip()
    confirm_status = str(values.get("confirm_status") or "").strip()
    todo, message = service.review(
        todo_id, operator=operator, result=result, confirm_status=confirm_status
    )
    if todo is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=todo)
