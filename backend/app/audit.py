"""审批链状态留痕：谁、在什么时刻、把记录从哪一步推到哪一步，全部落痕可查。

留痕挂在业务记录自身的 ``history`` 字段里，同时按业务模块同步一份到安全检查台账，
保证列表、详情、回执读到的是同一份状态；台账待办可以直接回溯到留痕条目。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# 安全检查台账在内存仓库里的表名：爆破链上需要安全确认/复核的待办都同步到这里
LEDGER_MODULE = "safety_ledger"


def now_label() -> str:
    """统一的时刻口径，带时区，避免各页面对时间显示不一致。"""
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def append_history(
    entry: dict[str, Any],
    *,
    action: str,
    from_status: str,
    to_status: str,
    operator: str,
    conclusion: str = "",
    note: str = "",
    backfilled: bool = False,
) -> dict[str, Any]:
    """在业务记录上追加一条状态留痕，并同步其当前状态口径。

    ``backfilled`` 用于存量历史记录：状态按当时的人工签字保留，只补登记不动数据。
    """
    entry.setdefault("history", [])
    record = {
        "seq": len(entry["history"]) + 1,
        "time": now_label(),
        "operator": operator or "值班管理员",
        "action": action,
        "from_status": from_status,
        "to_status": to_status,
        "conclusion": conclusion,
        "note": note,
        "backfilled": backfilled,
    }
    entry["history"].append(record)
    # 详情页展示“最后一次由谁推进”
    entry["last_operator"] = record["operator"]
    entry["last_action_at"] = record["time"]
    return record
