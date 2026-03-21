"""
每日收益追踪 API

端点：
  GET  /api/tracker/daily       — 查询每日记录
  GET  /api/tracker/monthly     — 月度汇总
  POST /api/tracker/snapshot    — 手动触发当天快照
  PATCH /api/tracker/{date}     — 编辑某天数据
  POST /api/tracker/import      — 上传 xlsx 导入
  GET  /api/tracker/export      — 导出 xlsx
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import io

from app.core.database import get_db
from app.services import tracker as tracker_svc

logger = logging.getLogger(__name__)
router = APIRouter()


# ── 查询 ───────────────────────────────────────────────────────────────────

@router.get("/daily")
async def get_daily(
    start: Optional[str] = None,
    end: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """查询每日记录，支持 start/end 日期过滤"""
    return await tracker_svc.get_daily_records(db, start, end)


@router.get("/monthly")
async def get_monthly(
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """月度汇总。不传参默认当月。传 year 不传 month 返回全年各月。"""
    today = date.today()
    if year and not month:
        # 返回全年各月
        results = []
        for m in range(1, 13):
            if year == today.year and m > today.month:
                break
            summary = await tracker_svc.get_monthly_summary(db, year, m)
            if summary.get("days", 0) > 0:
                results.append(summary)
        return results

    y = year or today.year
    m = month or today.month
    return await tracker_svc.get_monthly_summary(db, y, m)


# ── 快照 ───────────────────────────────────────────────────────────────────

@router.post("/snapshot")
async def trigger_snapshot(is_vip: bool = True):
    """手动触发当天快照。is_vip=true 时使用大会员参数（10%服务费+0CD天数）"""
    try:
        result = await tracker_svc.snapshot_daily(is_vip=is_vip)
        return {"ok": True, "data": result}
    except Exception as e:
        logger.exception("tracker snapshot failed: %s", e)
        raise HTTPException(status_code=502, detail=str(e))


# ── 编辑 ───────────────────────────────────────────────────────────────────

class TrackerUpdate(BaseModel):
    steamdt_index: Optional[float] = None
    notes: Optional[str] = None
    is_vip: Optional[bool] = None
    cost_basis: Optional[float] = None
    rented_count: Optional[int] = None
    rented_value: Optional[float] = None
    daily_income: Optional[float] = None
    total_inventory: Optional[int] = None
    inventory_value: Optional[float] = None


@router.patch("/{date_str}")
async def edit_record(
    date_str: str,
    body: TrackerUpdate,
    db: AsyncSession = Depends(get_db),
):
    """编辑某天的数据（支持 steamdt_index、notes 等字段）"""
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="无更新字段")

    result = await tracker_svc.update_record(db, date_str, fields)
    if result is None:
        raise HTTPException(status_code=404, detail=f"未找到 {date_str} 的记录")
    return result




# ── 导入 / 导出 ────────────────────────────────────────────────────────────

@router.post("/import")
async def import_excel(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """上传 xlsx 文件导入每日数据"""
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 文件")

    content = await file.read()
    result = await tracker_svc.import_from_excel(db, content)
    return {"ok": True, **result}


@router.get("/export")
async def export_excel(
    start: Optional[str] = None,
    end: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """导出每日数据为 xlsx"""
    data = await tracker_svc.export_to_excel(db, start, end)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=daily_tracker.xlsx"},
    )
