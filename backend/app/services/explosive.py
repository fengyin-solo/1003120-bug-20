"""爆破管理业务规则：审批链条状态机、字段校验、留痕与安全检查台账待办同步。

状态必须严格按 待审批 → 已审批 → 已爆破 → 已检查 推进：
- 不允许跳级（没有审批结论不许越过审批环节，也不许越过安全确认直接检查）；
- 不允许倒序回退；
- 同一条记录重复提交同一个动作只生效一次。

每次状态变更都写入 history（谁、什么时刻、从哪一步推到哪一步、结论/备注），
并同步刷新列表展示用的「爆破状态」字段与 pending/abnormal 标记；
安全检查台账的待办清单由这里的状态与留痕实时派生（见 inspection 服务）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.store import store

MODULE = "explosive"
REQUIRED_FIELDS = ["爆破编号", "爆破区域", "炸药用量"]
STATUS_ORDER = ["待审批", "已审批", "已爆破", "已检查"]
ACTION_RULES = {"提交审批": "已审批", "执行爆破": "已爆破", "爆后检查": "已检查"}
# 执行爆破前必须能在留痕里查到安全确认，防止安全确认环节被整个跳过。
SAFETY_CONFIRM_ACTION = "安全确认"
DEFAULT_ACTOR = "值班管理员"


def now_label() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class ExplosiveService:
    def __init__(self) -> None:
        # 数据仓库是进程级单例，服务在导入时构造一次；在这里统一做存量规整。
        self._bootstrap_legacy_rows()

    # ---------- 查询 ----------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("爆破编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    # ---------- 登记 ----------
    def create_entry(
        self, values: dict[str, Any], *, actor: str = DEFAULT_ACTOR
    ) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 其余业务字段（雷管用量、爆破时间、警戒范围、爆破人员）随登记单带入。
        for field in ["雷管用量", "爆破时间", "警戒范围", "爆破人员"]:
            if values.get(field) is not None:
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["history"] = [self._trace(actor or DEFAULT_ACTOR, "登记记录", "", STATUS_ORDER[0], "登记进入审批链")]
        # 展示字段与权威状态从第一条记录起就保持一致，避免回执和列表两样。
        entry["爆破状态"] = STATUS_ORDER[0]
        rows.append(entry)
        return entry, []

    # ---------- 状态流转 ----------
    def run_action(
        self,
        entry_id: int,
        action: str,
        *,
        actor: str = DEFAULT_ACTOR,
        conclusion: str = "",
        remark: str = "",
    ) -> tuple[dict[str, Any] | None, str, bool]:
        """执行审批链动作。

        返回 (记录, 说明, 是否实际生效)；被拒绝或重复提交时记录为 None 或原样返回、
        不产生第二条留痕。
        """
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"爆破记录 {entry_id} 不存在或已归档", False
        if entry.get("legacy_skipped") and not entry.get("legacy_reviewed"):
            return None, (
                "该记录是存量跳级记录，当时按人工签字保留现状，须先在安全检查台账完成复核，"
                "复核通过前不得继续在审批链上操作"
            ), False
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于爆破管理可执行范围", False

        current = str(entry.get("status") or "")
        current_idx = STATUS_ORDER.index(current) if current in STATUS_ORDER else -1
        target = ACTION_RULES[action]
        target_idx = STATUS_ORDER.index(target)

        if current_idx < 0:
            return None, f"当前状态「{current}」不在审批状态序列内，无法执行{action}", False
        if target_idx <= current_idx:
            # 同态重复提交与倒序回退一并在这里拦下。
            if target == current:
                return (
                    entry,
                    f"爆破记录已是「{current}」，{action}对同一张记录只生效一次，请勿重复提交",
                    False,
                )
            return (
                None,
                f"审批链只允许顺序推进：当前为「{current}」，不能{action}倒退回「{target}」",
                False,
            )
        if target_idx != current_idx + 1:
            return None, f"不允许跳级：须先完成「{STATUS_ORDER[current_idx + 1]}」，不能直接{action}", False

        note_parts = []
        if action == "提交审批":
            conclusion = str(conclusion or "").strip()
            if not conclusion:
                return None, "提交审批必须填写审批结论，没有审批结论不许跳过审批环节", False
            note_parts.append(f"审批结论：{conclusion}")
        elif action == "执行爆破":
            if not self._has_trace(entry, SAFETY_CONFIRM_ACTION):
                return None, (
                    "安全确认环节未完成：审批通过后须由安全员完成警戒、撤人等安全确认并签字，"
                    "才能执行爆破"
                ), False
        if str(remark or "").strip():
            note_parts.append(str(remark).strip())

        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = False
        entry["爆破状态"] = target
        entry.setdefault("history", []).append(
            self._trace(actor or DEFAULT_ACTOR, action, current, target, "；".join(note_parts))
        )
        return entry, f"爆破记录已{action}，状态由「{current}」推进到「{target}」", True

    def confirm_safety(
        self, entry_id: int, *, actor: str = DEFAULT_ACTOR, remark: str = ""
    ) -> tuple[dict[str, Any] | None, str]:
        """安全确认：审批通过后、执行爆破前的必经签字环节，不改变审批状态但必须留痕。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"爆破记录 {entry_id} 不存在或已归档"
        if entry.get("legacy_skipped") and not entry.get("legacy_reviewed"):
            return None, "存量跳级记录须先复核，复核通过前不得补做安全确认"
        current = str(entry.get("status") or "")
        if current != "已审批":
            return None, f"只有「已审批」待爆破的记录需要安全确认，当前状态为「{current}」"
        if self._has_trace(entry, SAFETY_CONFIRM_ACTION):
            return entry, "安全确认已签字，同一环节只确认一次，请勿重复提交"
        note = str(remark or "").strip() or "警戒到位、撤人清点完毕，具备爆破条件"
        entry.setdefault("history", []).append(
            self._trace(actor or DEFAULT_ACTOR, SAFETY_CONFIRM_ACTION, current, current, note)
        )
        return entry, "安全确认已签字留痕，具备执行爆破条件"

    def review_legacy(
        self, entry_id: int, *, actor: str = DEFAULT_ACTOR, opinion: str = ""
    ) -> tuple[dict[str, Any] | None, str]:
        """复核存量跳级记录：只核对当时的人工签字并销账，不改动、不补造审批状态。"""
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"爆破记录 {entry_id} 不存在或已归档"
        if not entry.get("legacy_skipped"):
            return None, "该记录不是存量跳级记录，无需复核"
        if entry.get("legacy_reviewed"):
            return entry, "该存量跳级记录已复核，请勿重复提交"
        opinion = str(opinion or "").strip()
        if not opinion:
            return None, "复核必须填写复核意见（认可人工签字或指出问题）"
        entry["legacy_reviewed"] = True
        entry["abnormal"] = False
        entry["pending"] = entry.get("status") != STATUS_ORDER[-1]
        entry.setdefault("history", []).append(
            self._trace(
                actor or DEFAULT_ACTOR,
                "存量跳级复核",
                str(entry.get("status") or ""),
                str(entry.get("status") or ""),
                f"复核意见：{opinion}；当时人工签字予以保留，不回改历史状态",
            )
        )
        return entry, "存量跳级记录已复核，人工签字结论保留，待办已销账"

    # ---------- 存量规整 ----------
    def _bootstrap_legacy_rows(self) -> None:
        """规整内存里的存量记录。

        - 展示字段「爆破状态」与权威 status 对齐（修回执/列表两样的老数据）；
        - 没有留痕的历史记录，按当时人工签字补一条 legacy 导入留痕；
          凡电子链条无法证明逐级推进的，标记 legacy_skipped 挂安全检查台账待复核。
        已经带完整留痕的记录不动。
        """
        for entry in store.rows(MODULE):
            status = str(entry.get("status") or STATUS_ORDER[0])
            if status not in STATUS_ORDER:
                status = STATUS_ORDER[0]
                entry["status"] = status
            entry["爆破状态"] = status
            entry.setdefault("pending", status != STATUS_ORDER[-1])

            history = entry.setdefault("history", [])
            if not history:
                # 老版本数据没有留痕，电子审批链无法证明逐级推进，按存量跳级处理。
                entry["legacy_skipped"] = True
                entry.setdefault("legacy_reviewed", False)
                entry["abnormal"] = True
                history.append(
                    self._trace(
                        "历史经办人（纸质工单签字）",
                        "存量补录",
                        "",
                        status,
                        "该记录由纸质台账迁入，线上缺逐级审批留痕，状态按当时人工签字保留，挂待办等复核",
                        source="legacy",
                    )
                )
            elif self._is_skipped_chain(entry, status):
                entry["legacy_skipped"] = True
                entry.setdefault("legacy_reviewed", False)
                entry["abnormal"] = True

            if entry.get("legacy_skipped") and not entry.get("legacy_reviewed"):
                entry["abnormal"] = True
                # 复核本身是待办，因此即使状态是已检查也要留在待处理口径里。
                entry["pending"] = True
            else:
                entry["pending"] = status != STATUS_ORDER[-1]

    def _is_skipped_chain(self, entry: dict[str, Any], status: str) -> bool:
        """从留痕判断电子链条是否逐级推进过；缺任一中间环节即为跳级。"""
        if entry.get("legacy_skipped"):
            return not entry.get("legacy_reviewed")
        target_idx = STATUS_ORDER.index(status)
        # 登记后的每一级都要能在系统留痕里找到对应的推进动作。
        progressed: set[int] = set()
        for item in entry.get("history", []):
            if item.get("source") == "system":
                to = item.get("to_status")
                action = item.get("action")
                if to in STATUS_ORDER:
                    progressed.add(STATUS_ORDER.index(to))
                if action == SAFETY_CONFIRM_ACTION:
                    progressed.add(-1)  # 安全确认存在性单独标记
        for idx in range(1, target_idx + 1):
            if idx not in progressed:
                return True
        # 已经推进到爆破之后的，安全确认也必须在系统留痕里。
        if target_idx >= STATUS_ORDER.index("已爆破") and -1 not in progressed:
            return True
        return False

    # ---------- 留痕 ----------
    def _trace(
        self,
        actor: str,
        action: str,
        from_status: str,
        to_status: str,
        note: str,
        *,
        source: str = "system",
    ) -> dict[str, Any]:
        return {
            "at": now_label(),
            "actor": actor or DEFAULT_ACTOR,
            "action": action,
            "from_status": from_status,
            "to_status": to_status,
            "note": note,
            "source": source,
        }

    def _has_trace(self, entry: dict[str, Any], action: str) -> bool:
        return any(item.get("action") == action for item in entry.get("history", []))


service = ExplosiveService()
