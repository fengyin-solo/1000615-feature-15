"""结果复核业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "review"
RESULT_MODULE = "result"
REQUIRED_FIELDS = ["复核编号", "关联结果", "复核项目"]
STATUS_ORDER = ["待复核", "复核中", "已通过", "需重测"]
ACTION_RULES = {"开始复核": "复核中", "确认通过": "已通过", "发起重测": "需重测"}
BATCH_ACTIONS = ["确认通过", "发起重测"]
# 批量处理只接受仍停留在「待复核」的记录，其余一律视为状态已变化、可能已被他人处理
BATCHABLE_STATUS = STATUS_ORDER[0]
NEGATIVE_ACTIONS = []
# 复核结论同步到关联检测结果：通过则结果确认，重测则退回待录入重新检测
RESULT_STATUS_BY_TARGET = {"已通过": "已确认", "需重测": "待录入"}


class ReviewService:
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
            rows = [row for row in rows if keyword in str(row.get("复核编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def stats(self) -> list[dict[str, Any]]:
        """看板计数：待复核量、本月通过量与需重测量，批量处理后前端会重新拉取。"""
        rows = store.rows(MODULE)
        month = date.today().strftime("%Y-%m")
        return [
            {"label": "待复核记录", "value": sum(1 for row in rows if row.get("status") == "待复核")},
            {"label": "本月通过数", "value": sum(
                1 for row in rows
                if row.get("status") == "已通过" and str(row.get("复核时间") or "").startswith(month)
            )},
            {"label": "需重测项数", "value": sum(1 for row in rows if row.get("status") == "需重测")},
        ]

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["复核状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"复核记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于结果复核可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        self._apply_transition(entry, action)
        synced = self._sync_linked_result(entry)
        message = f"复核记录已{action}"
        if synced:
            message += "，关联检测结果状态已同步"
        return entry, message

    def run_batch(
        self,
        *,
        action: str,
        ids: list[int],
        opinion: str | None,
        difference: str | None,
        reasons: dict[str, str],
    ) -> tuple[int, int, list[str]]:
        """批量确认通过 / 批量发起重测。

        先整批校验再整批落库：任何一条记录不合格（不存在、状态已变化、缺复核意见、
        重测条目缺单独原因）都不改动任何记录，并把问题逐条带回。
        """
        if action not in BATCH_ACTIONS:
            return 0, 0, [f"动作「{action}」不支持批量处理，仅支持：{'、'.join(BATCH_ACTIONS)}"]
        if not ids:
            return 0, 0, ["未勾选任何复核记录"]
        failures: list[str] = []
        entries: list[dict[str, Any]] = []
        seen: set[int] = set()
        for entry_id in ids:
            if entry_id in seen:
                continue
            seen.add(entry_id)
            entry = store.find(MODULE, entry_id)
            if entry is None:
                failures.append(f"复核记录 {entry_id}：不存在或已归档")
                continue
            label = str(entry.get("复核编号") or f"复核记录 {entry_id}")
            if entry.get("status") != BATCHABLE_STATUS:
                current = entry.get("status") or "未知"
                failures.append(f"{label}：状态已变化（当前为「{current}」），可能已被他人处理")
                continue
            if action == "发起重测" and not str(reasons.get(str(entry_id)) or "").strip():
                failures.append(f"{label}：发起重测必须为该条单独填写重测原因")
                continue
            entries.append(entry)
        if not str(opinion or "").strip():
            failures.append("整批缺少复核意见：请统一填写复核意见后再提交")
        if failures:
            return 0, 0, failures
        today = date.today().isoformat()
        synced = 0
        for entry in entries:
            entry["复核意见"] = str(opinion or "").strip()
            entry["差异说明"] = str(difference or "").strip()
            entry["复核时间"] = today
            if action == "发起重测":
                entry["重测原因"] = str(reasons.get(str(entry["id"])) or "").strip()
            self._apply_transition(entry, action)
            if self._sync_linked_result(entry):
                synced += 1
        return len(entries), synced, []

    def _apply_transition(self, entry: dict[str, Any], action: str) -> None:
        target = ACTION_RULES[action]
        entry["status"] = target
        entry["复核状态"] = target
        entry["pending"] = target in STATUS_ORDER[:2]
        entry["abnormal"] = action in NEGATIVE_ACTIONS

    def _sync_linked_result(self, entry: dict[str, Any]) -> bool:
        """按「关联结果」里的结果编号找到检测结果，把复核结论同步过去。"""
        code = str(entry.get("关联结果") or "").strip()
        target = RESULT_STATUS_BY_TARGET.get(str(entry.get("status") or ""))
        if not code or target is None:
            return False
        for row in store.rows(RESULT_MODULE):
            if str(row.get("结果编号") or "").strip() == code:
                row["status"] = target
                row["结果状态"] = target
                row["pending"] = target != "已确认"
                return True
        return False
