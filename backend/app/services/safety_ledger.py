"""安全检查台账：汇总爆破审批链上的安全确认待办与存量跳级复核挂账。

台账本身不直接改爆破记录状态，只负责列待办、核销/复核登记；
待办由爆破状态流转自动同步进来，保证“爆后检查”这一安全确认环节不会被跳过。
"""
from __future__ import annotations

from typing import Any

from app.audit import now_label
from app.store import store

MODULE = "safety_ledger"
EXPLOSIVE_MODULE = "explosive"
# 台账里仍然开口、需要人处理的状态
OPEN_STATUSES = ("待检查", "待复核")


class SafetyLedgerService:
    def list_todos(
        self,
        *,
        status: str | None = None,
        kind: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = list(store.rows(MODULE))
        if status:
            rows = [row for row in rows if row.get("status") == status]
        else:
            rows = [row for row in rows if row.get("status") in OPEN_STATUSES]
        if kind:
            rows = [row for row in rows if row.get("kind") == kind]
        # 待办在前，再按建立时刻倒序（同序时按 id）
        rows.sort(key=lambda row: (0 if row.get("status") in OPEN_STATUSES else 1, -int(row.get("id", 0))))
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def review(
        self,
        todo_id: int,
        *,
        operator: str,
        result: str,
        confirm_status: str = "",
    ) -> tuple[dict[str, Any] | None, str]:
        """人工复核一条存量跳级挂账：写明复核结论后核销。

        ``confirm_status`` 可选，用于把复核确认后的真实状态回写到爆破记录；
        不提供则只核销台账待办、保留记录现状（尊重当时人工签字）。
        """
        todo = store.find(MODULE, todo_id)
        if todo is None:
            return None, f"台账待办 {todo_id} 不存在"
        if todo.get("status") not in OPEN_STATUSES:
            return None, f"该待办已于 {todo.get('closed_at')} 由 {todo.get('closed_by')} 核销，无需重复处理"
        if not result.strip():
            return None, "请填写复核结论后再提交"

        if confirm_status:
            entry = store.find(EXPLOSIVE_MODULE, int(todo.get("entry_id", 0)))
            if entry is None:
                return None, "对应的爆破记录不存在或已归档"
            if confirm_status not in ("待审批", "已审批", "已爆破", "已检查"):
                return None, f"复核状态「{confirm_status}」不合法"
            entry["needs_review"] = False
            entry["status"] = confirm_status
            entry["pending"] = confirm_status != "已检查"
            todo["result"] = result.strip()
        else:
            todo["result"] = (str(todo.get("result") or "") + "；复核结论：" + result.strip()).strip("；")

        todo["status"] = "已核销"
        todo["closed_at"] = now_label()
        todo["closed_by"] = operator or "值班管理员"
        return todo, "复核已登记，待办已核销"
