"""结果复核接口：维护复核记录，覆盖开始复核、确认通过、发起重测与批量复核。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, BatchFailure, BatchResult, BatchReviewPayload, EntryPayload, PageResult
from app.services.review import ReviewService

router = APIRouter(prefix="/api/review", tags=["结果复核"])

service = ReviewService()

LIST_FIELDS = ["复核编号", "关联结果", "复核项目", "复核人", "复核意见", "复核时间", "差异说明", "复核状态"]
STATUSES = ["待复核", "复核中", "已通过", "需重测"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按复核编号检索"),
    status: str | None = Query(default=None, description="待复核、复核中、已通过、需重测"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按复核编号与状态过滤结果复核列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/summary")
def summary() -> dict[str, int]:
    """待复核计数、本月通过数、需重测项数；批量处理后前端会重新拉取。"""
    return service.summary()


@router.post("/batch", response_model=BatchResult)
def run_batch(payload: BatchReviewPayload) -> BatchResult:
    """批量确认通过/发起重测：任一记录不满足条件即整批拒绝，并逐条说明是哪几条、什么原因。"""
    processed, failures, message = service.run_batch(payload)
    if not message:
        message = (
            f"批量{payload.action.strip()}已整批拒绝，共 {len(failures)} 处问题，请逐条核对后重试"
            if failures else f"已批量处理 {len(processed)} 条复核记录"
        )
    return BatchResult(
        ok=not failures,
        message=message,
        processed=processed,
        failures=[BatchFailure(**failure) for failure in failures],
    )


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出结果复核清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "review", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条复核记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"复核记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条复核记录，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="复核记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条复核记录执行开始复核、确认通过、发起重测；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
