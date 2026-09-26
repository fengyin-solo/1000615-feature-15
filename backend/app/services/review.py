"""结果复核业务规则：状态流转、字段校验、批量复核与检测结果联动都收在这里。"""
from __future__ import annotations

import threading
from datetime import date
from typing import Any

from app.schemas import BatchReviewPayload
from app.store import store

MODULE = "review"
RESULT_MODULE = "result"
REQUIRED_FIELDS = ["复核编号", "关联结果", "复核项目"]
STATUS_ORDER = ["待复核", "复核中", "已通过", "需重测"]
ACTION_RULES = {"开始复核": "复核中", "确认通过": "已通过", "发起重测": "需重测"}
NEGATIVE_ACTIONS = []
# 批量复核只接受结论性动作；开始复核仍走单条动作
BATCH_ACTIONS = {"确认通过", "发起重测"}
# 只有仍在复核流程中的记录允许批量处理，进入终态的视为已被别人处理
ACTIONABLE_STATUSES = {"待复核", "复核中"}
FINAL_STATUSES = {"已通过", "需重测"}
# 复核结论如何联动关联检测结果的内部状态
RESULT_SYNC = {"确认通过": "已确认", "发起重测": "待录入"}
# 校验与落库必须串行：两个批量请求并发时，后到的请求要能看到前一批已改的状态，
# 从而按“状态已变化”逐条拒绝，而不是互相覆盖
_BATCH_LOCK = threading.Lock()


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

    def summary(self) -> dict[str, int]:
        """待复核计数、本月通过数、需重测项数；批量处理后前端会重新拉取。"""
        rows = store.rows(MODULE)
        month = date.today().strftime("%Y-%m")
        return {
            "待复核记录": sum(1 for row in rows if row.get("status") in ACTIONABLE_STATUSES),
            "本月通过数": sum(
                1
                for row in rows
                if row.get("status") == "已通过" and str(row.get("复核时间") or "").startswith(month)
            ),
            "需重测项数": sum(1 for row in rows if row.get("status") == "需重测"),
        }

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"复核记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于结果复核可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target not in FINAL_STATUSES
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        for field in ("复核人", "复核意见", "差异说明"):
            text = str((values or {}).get(field) or "").strip()
            if text:
                entry[field] = text
        if action in BATCH_ACTIONS:
            entry["复核状态"] = target
            entry["复核时间"] = date.today().isoformat()
            self._sync_result(entry, action)
        return entry, f"复核记录已{action}"

    def run_batch(
        self,
        payload: BatchReviewPayload,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        """批量确认通过/发起重测。

        先对整批做校验：任何一条记录不存在、状态已变化，或整批缺少复核意见、
        重测条目缺单独原因，都整批拒绝并逐条列出问题；全部通过后才统一落库，
        不会出现只成功一半的情况。
        """
        action = payload.action.strip()
        if action not in BATCH_ACTIONS:
            return [], [{"id": None, "复核编号": "—", "原因": f"动作「{action}」不支持批量处理，请逐条执行"}], ""
        # 去重并保持勾选顺序，避免同一条被重复计为多份
        entry_ids = list(dict.fromkeys(payload.ids))
        if not entry_ids:
            return [], [{"id": None, "复核编号": "—", "原因": "请先勾选需要批量处理的复核记录"}], ""
        with _BATCH_LOCK:
            return self._run_batch_locked(action, entry_ids, payload)

    def _run_batch_locked(
        self,
        action: str,
        entry_ids: list[int],
        payload: BatchReviewPayload,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        opinion = payload.复核意见.strip()
        failures: list[dict[str, Any]] = []
        if not opinion:
            failures.append({
                "id": None,
                "复核编号": "—",
                "原因": "缺少复核意见：批量处理必须统一填写复核意见",
            })
        entries: list[dict[str, Any]] = []
        for entry_id in entry_ids:
            entry = store.find(MODULE, entry_id)
            if entry is None:
                failures.append({
                    "id": entry_id,
                    "复核编号": "—",
                    "原因": f"复核记录 {entry_id} 不存在或已归档",
                })
                continue
            status = str(entry.get("status") or "")
            if status not in ACTIONABLE_STATUSES:
                failures.append({
                    "id": entry_id,
                    "复核编号": str(entry.get("复核编号") or ""),
                    "原因": f"当前状态为「{status}」，可能已被别人处理，请刷新列表后重试",
                })
                continue
            if action == "发起重测" and not payload.重测原因.get(str(entry_id), "").strip():
                failures.append({
                    "id": entry_id,
                    "复核编号": str(entry.get("复核编号") or ""),
                    "原因": "发起重测必须为该条单独写明重测原因",
                })
                continue
            entries.append(entry)
        if failures:
            return [], failures, f"批量{action}已整批拒绝，共 {len(failures)} 处问题，请逐条核对后重试"
        today = date.today().isoformat()
        target = ACTION_RULES[action]
        for entry in entries:
            entry["status"] = target
            entry["pending"] = False
            entry["abnormal"] = False
            entry["复核状态"] = target
            entry["复核时间"] = today
            entry["复核意见"] = opinion
            entry["差异说明"] = payload.差异说明.strip()
            reviewer = payload.复核人.strip()
            if reviewer:
                entry["复核人"] = reviewer
            if action == "发起重测":
                entry["重测原因"] = payload.重测原因.get(str(entry["id"]), "").strip()
            self._sync_result(entry, action)
        return entries, [], f"已批量{action} {len(entries)} 条复核记录"

    def _sync_result(self, entry: dict[str, Any], action: str) -> None:
        """按复核结论联动关联检测结果的状态；找不到关联结果时跳过，不影响复核本身。"""
        target = RESULT_SYNC.get(action)
        if not target:
            return
        result_no = str(entry.get("关联结果") or "").strip()
        if not result_no:
            return
        for row in store.rows(RESULT_MODULE):
            if str(row.get("结果编号") or "") == result_no:
                row["status"] = target
                row["pending"] = target != "已确认"
                row["结果状态"] = target
