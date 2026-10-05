"""爆破管理业务规则：状态流转、字段校验、留痕与安全确认台账同步都收在这里。

审批链是一条直线，任何一步都不能越位：

    待审批 ──提交审批──▶ 已审批 ──执行爆破──▶ 已爆破 ──爆后检查──▶ 已检查

规则：
* 只能推进到当前状态的紧邻下一步；跳级（没有审批结论就爆破/检查）当场拒绝；
* 不允许倒序回退，倒序请求当场拒绝并写明原因；
* 同一张记录重复提交同一个动作只生效一次（再次提交按幂等拒绝，不重复留痕）；
* 每次状态变更都留痕（操作人、时刻、动作、起止状态、审批结论）；
* “已爆破 → 已检查”是安全确认环节，进入“已爆破”即同步一条安全检查台账待办，
  爆后检查通过后核销，安全确认不可跳过。
"""
from __future__ import annotations

from typing import Any

from app.audit import append_history
from app.store import store

MODULE = "explosive"
LEDGER_MODULE = "safety_ledger"
REQUIRED_FIELDS = ["爆破编号", "爆破区域", "炸药用量"]
STATUS_ORDER = ["待审批", "已审批", "已爆破", "已检查"]
# 动作只能把记录推到当前状态的下一步；键为动作，值为其目标状态
ACTION_RULES = {"提交审批": "已审批", "执行爆破": "已爆破", "爆后检查": "已检查"}
# 哪些动作必须带审批/检查结论，没有结论不许推进
CONCLUSION_REQUIRED = {"提交审批": "审批结论（同意/不同意 + 签字）", "爆后检查": "爆后安全检查结论"}
# 进入“已爆破”时同步安全检查台账待办；完成“已检查”时核销
SAFETY_PENDING_STATUS = "已爆破"


class ExplosiveService:
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

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        # 其余选填信息原样保留
        for field in ("雷管用量", "爆破时间", "警戒范围", "爆破人员"):
            if values.get(field) is not None:
                entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry["history"] = []
        entry["needs_review"] = False
        rows.append(entry)
        return entry, []

    # ------------------------------------------------------------------
    # 状态流转：核心闸门
    # ------------------------------------------------------------------
    def run_action(
        self,
        entry_id: int,
        action: str,
        *,
        operator: str = "值班管理员",
        conclusion: str = "",
        note: str = "",
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"爆破记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于爆破管理可执行范围"

        current = str(entry.get("status") or "")
        target = ACTION_RULES[action]

        # 当前状态不在合法序列里：数据本身异常，拒绝任何流转，交人工复核
        if current not in STATUS_ORDER:
            return None, f"记录当前状态「{current}」不在审批链内，请先在安全检查台账中复核"

        current_index = STATUS_ORDER.index(current)
        target_index = STATUS_ORDER.index(target)

        # 倒序回退当场拒绝
        if target_index < current_index:
            return None, (
                f"不允许倒序回退：记录当前为「{current}」，动作「{action}」"
                f"要把状态退回「{target}」，审批链只能按 {' → '.join(STATUS_ORDER)} 顺序推进"
            )

        # 重复提交同一动作（目标状态已经是当前状态）：只生效一次，幂等拒绝
        if target_index == current_index:
            return None, f"记录已经是「{current}」，动作「{action}」此前已生效，无需重复提交"

        # 跳级：目标不是当前状态的紧邻下一步
        if target_index != current_index + 1:
            missing_step = STATUS_ORDER[current_index + 1]
            return None, (
                f"不允许跳级：记录当前为「{current}」，须先推进到「{missing_step}」，"
                f"不能直接执行「{action}」到「{target}」"
            )

        # 审批/检查结论缺失：没有审批结论不许推进
        if action in CONCLUSION_REQUIRED and not conclusion.strip():
            return None, f"缺少{CONCLUSION_REQUIRED[action]}，不能{action}"

        # 闸门通过，落状态并留痕
        entry["status"] = target
        entry["爆破状态"] = target  # 展示字段与权威状态同源，避免列表与回执两样
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = False
        record = append_history(
            entry,
            action=action,
            from_status=current,
            to_status=target,
            operator=operator,
            conclusion=conclusion.strip(),
            note=note.strip(),
        )
        self._sync_safety_ledger(entry, record)
        return entry, f"爆破记录已{action}：{current} → {target}"

    # ------------------------------------------------------------------
    # 安全检查台账同步：已爆破待检查 -> 待办；已检查 -> 核销
    # ------------------------------------------------------------------
    def _sync_safety_ledger(self, entry: dict[str, Any], record: dict[str, Any]) -> None:
        ledger = store.rows(LEDGER_MODULE)
        ref_id = f"explosive:{entry['id']}"
        existing = next((item for item in ledger if item.get("ref") == ref_id), None)

        if entry["status"] == SAFETY_PENDING_STATUS:
            # 进入“已爆破”：必须有一条待办等安全确认，防止爆后检查环节被跳过
            if existing is None:
                ledger.append({
                    "id": max((int(row.get("id", 0)) for row in ledger), default=0) + 1,
                    "ref": ref_id,
                    "module": MODULE,
                    "entry_id": entry["id"],
                    "title": f"爆破后安全确认：{entry.get('爆破编号', entry['id'])}（{entry.get('爆破区域', '')}）",
                    "kind": "爆后安全检查",
                    "status": "待检查",
                    "created_at": record["time"],
                    "created_by": record["operator"],
                    "closed_at": None,
                    "closed_by": None,
                    "result": "",
                })
        elif entry["status"] == STATUS_ORDER[-1] and existing is not None:
            # 完成爆后检查：核销待办，回填结论
            existing["status"] = "已核销"
            existing["closed_at"] = record["time"]
            existing["closed_by"] = record["operator"]
            existing["result"] = record["conclusion"]

    # ------------------------------------------------------------------
    # 存量历史记录：按当时人工签字保留，跳级的挂复核待办
    # ------------------------------------------------------------------
    def backfill_legacy(self) -> int:
        """把存量记录按其现状补登留痕；缺中间环节的挂到安全检查台账等人工复核。

        只在服务启动时跑一次：不改动记录当前状态（尊重当时人工签字），
        只为缺留痕的记录补一条“历史补录”，并把跳级记录挂入复核待办。
        """
        rows = store.rows(MODULE)
        ledger = store.rows(LEDGER_MODULE)
        backfilled = 0
        for entry in rows:
            current = str(entry.get("status") or "")
            if current not in STATUS_ORDER:
                continue
            entry.setdefault("needs_review", False)
            if not entry.get("history"):
                operator = str(entry.get("签字人") or "历史人工签字")
                append_history(
                    entry,
                    action="历史补录",
                    from_status=current,
                    to_status=current,
                    operator=operator,
                    conclusion="存量数据按当时人工签字保留",
                    note="系统上线前历史记录",
                    backfilled=True,
                )
                backfilled += 1
            # 列表展示用的“爆破状态”字段统一向权威状态 status 对齐，
            # 历史人工签字的保留括注，避免列表与详情/回执显示成两样
            legacy_mark = "（历史人工签字）" if entry.get("history") and any(
                item.get("backfilled") for item in entry["history"]
            ) else ""
            if entry.get("爆破状态") != current:
                entry["爆破状态"] = current + legacy_mark

            # 存量记录只有一条补录痕迹，系统无法还原其上线前走过哪些环节，
            # 因此不拿“缺数字留痕”反推定罪，而是按当前停留状态决定安全口径：
            #   待审批/已审批 —— 正常停留，无需挂账；
            #   已爆破       —— 安全确认尚未做，补挂爆后检查待办，不让该环节缺失；
            #   已检查       —— 终态按当时人工签字保留，但无法核验爆后安全确认，
            #                   挂存量复核待办，由人工复核签字。
            ref_id = f"explosive:{entry['id']}"
            has_open_ledger = any(item.get("ref") == ref_id for item in ledger)
            if has_open_ledger:
                continue
            if current == "已检查":
                entry["needs_review"] = True
                ledger.append({
                    "id": max((int(row.get("id", 0)) for row in ledger), default=0) + 1,
                    "ref": ref_id,
                    "module": MODULE,
                    "entry_id": entry["id"],
                    "title": f"历史记录复核：{entry.get('爆破编号', entry['id'])} 当前为「{current}」",
                    "kind": "存量跳级复核",
                    "status": "待复核",
                    "created_at": str(entry.get("last_action_at") or ""),
                    "created_by": "系统补录",
                    "closed_at": None,
                    "closed_by": None,
                    "result": "上线前已到终态，爆后安全确认环节无法线上核验，按当时人工签字保留，待人工复核",
                })
            elif current == SAFETY_PENDING_STATUS:
                # 停在“已爆破”：安全确认尚未完成，补挂爆后检查待办，不跳过该环节
                ledger.append({
                    "id": max((int(row.get("id", 0)) for row in ledger), default=0) + 1,
                    "ref": ref_id,
                    "module": MODULE,
                    "entry_id": entry["id"],
                    "title": f"爆破后安全确认：{entry.get('爆破编号', entry['id'])}（{entry.get('爆破区域', '')}）",
                    "kind": "爆后安全检查",
                    "status": "待检查",
                    "created_at": str(entry.get("last_action_at") or ""),
                    "created_by": str(entry.get("签字人") or "历史人工签字"),
                    "closed_at": None,
                    "closed_by": None,
                    "result": "存量记录停在已爆破，补挂安全确认待办",
                })
        return backfilled
