"""安全检查台账：待办清单由爆破审批链的状态与留痕实时派生，不复制状态。

两类待办：
1. 爆后检查待办：爆破记录推进到「已爆破」后自动入清单，完成「爆后检查」自动销账；
2. 存量跳级复核待办：历史上已跳级的记录按人工签字保留状态，挂在这里等人工复核，
   复核动作由爆破服务执行并留痕。
"""
from __future__ import annotations

from typing import Any

from app.services.explosive import service as explosive_service
from app.store import store

MODULE = "explosive"


class InspectionService:
    def list_todos(self, *, kind: str | None = None) -> list[dict[str, Any]]:
        todos: list[dict[str, Any]] = []
        for entry in store.rows(MODULE):
            status = str(entry.get("status") or "")
            if status == "已爆破":
                todos.append(self._blast_check_todo(entry))
            if entry.get("legacy_skipped") and not entry.get("legacy_reviewed"):
                todos.append(self._legacy_review_todo(entry))
        if kind:
            todos = [todo for todo in todos if todo["kind"] == kind]
        todos.sort(key=lambda todo: (todo["kind"] == "blast_check", todo["entry_id"]))
        return todos

    def review_legacy(
        self, entry_id: int, *, actor: str = "值班管理员", opinion: str = ""
    ) -> tuple[dict[str, Any] | None, str]:
        return explosive_service.review_legacy(entry_id, actor=actor, opinion=opinion)

    def _blast_check_todo(self, entry: dict[str, Any]) -> dict[str, Any]:
        last = self._last_trace(entry, "执行爆破")
        return {
            "todo_id": f"blast-check-{entry.get('id')}",
            "kind": "blast_check",
            "kind_label": "爆后安全检查",
            "entry_id": entry.get("id"),
            "爆破编号": entry.get("爆破编号"),
            "爆破区域": entry.get("爆破区域"),
            "status": entry.get("status"),
            "title": f"{entry.get('爆破编号')} 已爆破，等待爆后检查",
            "created_at": (last or {}).get("at", ""),
            "operator": (last or {}).get("actor", ""),
            "note": (last or {}).get("note", ""),
        }

    def _legacy_review_todo(self, entry: dict[str, Any]) -> dict[str, Any]:
        legacy_traces = [
            item for item in entry.get("history", []) if item.get("source") == "legacy"
        ]
        last = legacy_traces[-1] if legacy_traces else None
        return {
            "todo_id": f"legacy-review-{entry.get('id')}",
            "kind": "legacy_review",
            "kind_label": "存量跳级复核",
            "entry_id": entry.get("id"),
            "爆破编号": entry.get("爆破编号"),
            "爆破区域": entry.get("爆破区域"),
            "status": entry.get("status"),
            "title": f"{entry.get('爆破编号')} 为存量跳级记录（当前{entry.get('status')}），等待复核人工签字",
            "created_at": (last or {}).get("at", ""),
            "operator": (last or {}).get("actor", ""),
            "note": (last or {}).get("note", ""),
        }

    def _last_trace(self, entry: dict[str, Any], action: str) -> dict[str, Any] | None:
        traces = [item for item in entry.get("history", []) if item.get("action") == action]
        return traces[-1] if traces else None


service = InspectionService()
