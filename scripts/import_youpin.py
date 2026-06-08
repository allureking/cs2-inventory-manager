#!/usr/bin/env python3
"""
悠悠有品交易记录导入 — 从 CSV/JSON 文件或 API 导入购买记录到 inventory_item.purchase_price

匹配策略（优先级递减）：
  1. marketHashName 精确匹配（英文名）
  2. 磨损值 abrade 精确匹配（同名多件时区分个体）
  3. 中文名 fallback（API 数据可能只有中文名）

同名多件饰品按购入时间升序依次绑定（FIFO）。

用法:
  python scripts/import_youpin.py api              # 从悠悠 API 拉取购买记录
  python scripts/import_youpin.py csv  records.csv  # 从 CSV 文件导入
  python scripts/import_youpin.py json records.json # 从 JSON 文件导入
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import asyncio
import csv
import json
import logging
from dataclasses import dataclass, field
from typing import Optional

from rich.console import Console
from rich.table import Table
from sqlalchemy import func, select

from app.core.constants import ACTIVE_STATUSES
from app.core.database import AsyncSessionLocal, init_db
from app.models.db_models import InventoryItem

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)
console = Console()


@dataclass
class BuyRecord:
    market_hash_name: str
    name_cn: str = ""
    price: float = 0.0
    quantity: int = 1
    date: str = ""
    abrade: Optional[float] = None
    commodity_id: Optional[int] = None
    asset_id: str = ""
    platform: str = "YOUPIN"


@dataclass
class MatchReport:
    matched: list = field(default_factory=list)
    unmatched: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    already_has_cost: int = 0


def _parse_csv(path: str) -> list[BuyRecord]:
    """
    解析 CSV 文件。支持的列名（大小写不敏感）:
      market_hash_name / marketHashName — 英文名（必需或 name_cn 二选一）
      name / name_cn                   — 中文名
      price / purchase_price / totalAmount — 单价（元）
      quantity / qty / count            — 数量（默认1）
      date / purchase_date              — 购入日期
      abrade                            — 磨损值
      commodity_id                      — 悠悠商品ID
      asset_id                          — Steam asset ID
    """
    records = []
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            console.print("[red]CSV 文件无表头[/red]")
            return []

        col_map = {c.lower().strip(): c for c in reader.fieldnames}

        def _get(row: dict, *keys) -> str:
            for k in keys:
                for orig_key, orig_col in col_map.items():
                    if orig_key == k.lower():
                        v = row.get(orig_col, "").strip()
                        if v:
                            return v
            return ""

        for row in reader:
            hash_name = _get(row, "market_hash_name", "marketHashName", "markethashname",
                             "commodity_hash_name", "commodityHashName")
            name_cn = _get(row, "name", "name_cn", "namecn", "commodity_name")
            if not hash_name and not name_cn:
                continue

            price_str = _get(row, "price", "purchase_price", "totalAmount", "total_amount", "unit_price")
            qty_str = _get(row, "quantity", "qty", "count", "num")
            date_str = _get(row, "date", "purchase_date", "purchaseDate")
            abrade_str = _get(row, "abrade", "wear", "float")
            cid_str = _get(row, "commodity_id", "commodityId")
            aid_str = _get(row, "asset_id", "assetId")

            price = 0.0
            if price_str:
                try:
                    price = float(price_str)
                except ValueError:
                    pass

            qty = 1
            if qty_str:
                try:
                    qty = max(1, int(float(qty_str)))
                except ValueError:
                    pass

            abrade = None
            if abrade_str:
                try:
                    v = float(abrade_str)
                    abrade = v if v > 0 else None
                except ValueError:
                    pass

            cid = None
            if cid_str:
                try:
                    cid = int(cid_str)
                except ValueError:
                    pass

            records.append(BuyRecord(
                market_hash_name=hash_name,
                name_cn=name_cn,
                price=price,
                quantity=qty,
                date=date_str,
                abrade=abrade,
                commodity_id=cid,
                asset_id=aid_str,
            ))
    return records


def _parse_json(path: str) -> list[BuyRecord]:
    """
    解析 JSON 文件。支持两种格式：
      1. 悠悠 API 原始格式（带 productDetail 嵌套）
      2. 扁平格式（与 CSV 字段名一致）
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict):
        data = data.get("data") or data.get("Data") or data.get("list") or data.get("records") or [data]
    if not isinstance(data, list):
        console.print("[red]JSON 结构无法识别[/red]")
        return []

    records = []
    for item in data:
        detail = item.get("productDetail") or {}

        hash_name = (
            detail.get("commodityHashName") or detail.get("marketHashName") or
            item.get("market_hash_name") or item.get("marketHashName") or
            item.get("commodityHashName") or ""
        ).strip()

        name_cn = (
            detail.get("name") or detail.get("shortName") or
            item.get("name") or item.get("name_cn") or ""
        ).strip()

        if not hash_name and not name_cn:
            continue

        # price: API format uses totalAmount in 分, flat format uses 元
        price = 0.0
        if item.get("totalAmount") is not None:
            try:
                price = float(item["totalAmount"]) / 100
            except (TypeError, ValueError):
                pass
        elif item.get("price") is not None:
            try:
                price = float(item["price"])
            except (TypeError, ValueError):
                pass

        qty = 1
        for qk in ("commodityNum", "count", "quantity", "qty"):
            if item.get(qk):
                try:
                    qty = max(1, int(item[qk]))
                except (TypeError, ValueError):
                    pass
                break

        date_str = ""
        for dk in ("createOrderTime", "finishOrderTime", "payTime", "date", "purchase_date"):
            v = item.get(dk)
            if v:
                if isinstance(v, (int, float)) and v > 1e12:
                    from datetime import datetime, timezone
                    try:
                        date_str = datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                    except (OSError, ValueError):
                        pass
                elif isinstance(v, str) and len(v) >= 8:
                    date_str = v[:10]
                if date_str:
                    break

        abrade = None
        raw_abrade = detail.get("abrade") or detail.get("commodityAbrade") or item.get("abrade")
        if raw_abrade:
            try:
                v = float(raw_abrade)
                abrade = v if v > 0 else None
            except (TypeError, ValueError):
                pass

        cid = None
        for ck in ("commodityId",):
            v = detail.get(ck) or item.get(ck)
            if v:
                try:
                    cid = int(v)
                except (TypeError, ValueError):
                    pass
                break

        aid = str(detail.get("assetId") or detail.get("assertId") or item.get("asset_id") or "").strip()

        records.append(BuyRecord(
            market_hash_name=hash_name,
            name_cn=name_cn,
            price=price / qty if qty > 1 else price,
            quantity=qty,
            date=date_str,
            abrade=abrade,
            commodity_id=cid,
            asset_id=aid,
        ))
    return records


async def _fetch_api_records() -> list[BuyRecord]:
    """从悠悠 API 拉取全部购买记录"""
    from app.services.youpin import fetch_buy_records

    all_records: list[dict] = []
    page = 1
    while page <= 200:
        try:
            batch = await fetch_buy_records(page=page, page_size=30)
        except Exception as e:
            console.print(f"[red]API 拉取第 {page} 页失败: {e}[/red]")
            break
        if not batch:
            break
        all_records.extend(batch)
        if len(batch) < 30:
            break
        page += 1

    console.print(f"从 API 拉取到 [cyan]{len(all_records)}[/cyan] 条购买记录")

    records = []
    for item in all_records:
        detail = item.get("productDetail") or {}
        hash_name = (detail.get("commodityHashName") or "").strip()
        name_cn = (detail.get("name") or detail.get("shortName") or "").strip()
        if not hash_name and not name_cn:
            continue

        price = 0.0
        if item.get("totalAmount"):
            try:
                price = float(item["totalAmount"]) / 100
            except (TypeError, ValueError):
                pass

        qty = 1
        for qk in ("commodityNum", "count", "quantity"):
            if item.get(qk):
                try:
                    qty = max(1, int(item[qk]))
                except (TypeError, ValueError):
                    pass
                break

        date_str = ""
        for dk in ("createOrderTime", "finishOrderTime", "payTime"):
            v = item.get(dk)
            if v:
                from datetime import datetime, timezone
                try:
                    date_str = datetime.fromtimestamp(int(v) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
                except (OSError, ValueError, TypeError):
                    pass
                if date_str:
                    break

        abrade = None
        raw = detail.get("abrade") or detail.get("commodityAbrade")
        if raw:
            try:
                v = float(raw)
                abrade = v if v > 0 else None
            except (TypeError, ValueError):
                pass

        cid = None
        v = detail.get("commodityId")
        if v:
            try:
                cid = int(v)
            except (TypeError, ValueError):
                pass

        aid = str(detail.get("assetId") or detail.get("assertId") or "").strip()

        per_price = price / qty if qty > 1 else price
        records.append(BuyRecord(
            market_hash_name=hash_name,
            name_cn=name_cn,
            price=per_price,
            quantity=qty,
            date=date_str,
            abrade=abrade,
            commodity_id=cid,
            asset_id=aid,
        ))
    return records


async def do_import(records: list[BuyRecord], dry_run: bool = False, overwrite: bool = False) -> MatchReport:
    """
    将购买记录匹配到 inventory_item 并写入 purchase_price。

    匹配优先级:
      1. commodity_id 精确匹配
      2. asset_id 精确匹配（仅 STEAM_PROTECTED 类型）
      3. market_hash_name + abrade 精确匹配
      4. market_hash_name 匹配（无 abrade 的库存优先）
      5. 中文名 name_cn fallback（同上策略）

    同名多件按 purchase_date 升序 FIFO 绑定。
    """
    report = MatchReport()

    async with AsyncSessionLocal() as db:
        query = select(InventoryItem).where(InventoryItem.status.in_(ACTIVE_STATUSES))
        if not overwrite:
            query = query.where(InventoryItem.purchase_price.is_(None))

        result = await db.execute(query)
        all_items = list(result.scalars().all())

        if not overwrite:
            # Count items already having cost (for report)
            count_r = await db.execute(
                select(func.count()).where(
                    InventoryItem.status.in_(ACTIVE_STATUSES),
                    InventoryItem.purchase_price.isnot(None),
                )
            )
            report.already_has_cost = count_r.scalar() or 0

        by_commodity: dict[int, list[InventoryItem]] = {}
        by_asset: dict[str, list[InventoryItem]] = {}
        by_hash: dict[str, list[InventoryItem]] = {}
        by_cn: dict[str, list[InventoryItem]] = {}

        for it in all_items:
            if it.youpin_commodity_id:
                by_commodity.setdefault(it.youpin_commodity_id, []).append(it)
            if it.asset_id:
                by_asset.setdefault(it.asset_id, []).append(it)
            by_hash.setdefault(it.market_hash_name, []).append(it)
            if it.name:
                by_cn.setdefault(it.name, []).append(it)

        claimed: set[int] = set()

        # Sort records by date (FIFO)
        def _sort_key(r: BuyRecord):
            return r.date or "9999-99-99"
        records.sort(key=_sort_key)

        for rec in records:
            if rec.price <= 0:
                report.skipped.append({"name": rec.market_hash_name or rec.name_cn, "reason": "价格为0"})
                continue

            for _ in range(rec.quantity):
                item = None
                match_method = ""

                # Strategy 1: commodity_id
                if rec.commodity_id and rec.commodity_id in by_commodity:
                    for c in by_commodity[rec.commodity_id]:
                        if c.id not in claimed:
                            item = c
                            match_method = "commodity_id"
                            break

                # Strategy 2: asset_id (STEAM_PROTECTED only)
                if not item and rec.asset_id and rec.asset_id in by_asset:
                    for c in by_asset[rec.asset_id]:
                        if c.id not in claimed and c.class_id == "STEAM_PROTECTED":
                            item = c
                            match_method = "asset_id"
                            break

                # Strategy 3: hash_name + abrade exact
                if not item and rec.market_hash_name and rec.abrade is not None:
                    candidates = by_hash.get(rec.market_hash_name, [])
                    for c in candidates:
                        if c.id not in claimed and c.abrade is not None and abs(c.abrade - rec.abrade) < 0.0001:
                            item = c
                            match_method = "hash+abrade"
                            break

                # Strategy 4: hash_name (prefer items without abrade first, then any)
                if not item and rec.market_hash_name:
                    candidates = by_hash.get(rec.market_hash_name, [])
                    # Prefer no-abrade items first (generic match)
                    for c in candidates:
                        if c.id not in claimed and c.abrade is None:
                            item = c
                            match_method = "hash_name"
                            break
                    if not item:
                        for c in candidates:
                            if c.id not in claimed:
                                item = c
                                match_method = "hash_name"
                                break

                # Strategy 5: Chinese name fallback
                if not item and rec.name_cn:
                    candidates = by_cn.get(rec.name_cn, [])
                    if rec.abrade is not None:
                        for c in candidates:
                            if c.id not in claimed and c.abrade is not None and abs(c.abrade - rec.abrade) < 0.0001:
                                item = c
                                match_method = "cn_name+abrade"
                                break
                    if not item:
                        for c in candidates:
                            if c.id not in claimed and c.abrade is None:
                                item = c
                                match_method = "cn_name"
                                break
                        if not item:
                            for c in candidates:
                                if c.id not in claimed:
                                    item = c
                                    match_method = "cn_name"
                                    break

                if not item:
                    report.unmatched.append({
                        "name": rec.market_hash_name or rec.name_cn,
                        "price": rec.price,
                        "date": rec.date,
                        "abrade": rec.abrade,
                    })
                    break  # No more unclaimed items for this name

                claimed.add(item.id)
                if not dry_run:
                    item.purchase_price = rec.price
                    if rec.date:
                        item.purchase_date = rec.date
                    item.purchase_platform = rec.platform

                report.matched.append({
                    "name": rec.market_hash_name or rec.name_cn,
                    "item_id": item.id,
                    "asset_id": item.asset_id,
                    "price": rec.price,
                    "date": rec.date,
                    "method": match_method,
                })

        if not dry_run:
            await db.commit()

    return report


def _print_report(report: MatchReport, dry_run: bool):
    mode = "[yellow]DRY RUN[/yellow] " if dry_run else ""

    console.print()
    console.rule(f"{mode}匹配报告")

    # Summary
    summary = Table(show_header=False, box=None, padding=(0, 2))
    summary.add_column(style="bold")
    summary.add_column(style="cyan", justify="right")
    summary.add_row("成功匹配", str(len(report.matched)))
    summary.add_row("未匹配", str(len(report.unmatched)))
    summary.add_row("跳过（无效价格）", str(len(report.skipped)))
    summary.add_row("库存已有成本", str(report.already_has_cost))
    console.print(summary)

    # Match method breakdown
    if report.matched:
        method_counts: dict[str, int] = {}
        for m in report.matched:
            method_counts[m["method"]] = method_counts.get(m["method"], 0) + 1
        console.print()
        t = Table(title="匹配策略分布", show_lines=False)
        t.add_column("策略", style="green")
        t.add_column("数量", justify="right")
        for method, count in sorted(method_counts.items(), key=lambda x: -x[1]):
            t.add_row(method, str(count))
        console.print(t)

    # Top matched items
    if report.matched and len(report.matched) <= 30:
        console.print()
        t = Table(title="匹配明细", show_lines=False)
        t.add_column("#", justify="right", style="dim")
        t.add_column("饰品名", max_width=50)
        t.add_column("价格", justify="right", style="cyan")
        t.add_column("日期")
        t.add_column("策略", style="green")
        for i, m in enumerate(report.matched, 1):
            t.add_row(str(i), m["name"], f"¥{m['price']:.2f}", m["date"] or "-", m["method"])
        console.print(t)

    # Unmatched items
    if report.unmatched:
        console.print()
        t = Table(title="[red]未匹配记录[/red]", show_lines=False)
        t.add_column("#", justify="right", style="dim")
        t.add_column("饰品名", max_width=50)
        t.add_column("价格", justify="right", style="red")
        t.add_column("日期")
        uniq: dict[str, dict] = {}
        for u in report.unmatched:
            key = u["name"]
            if key in uniq:
                uniq[key]["count"] += 1
            else:
                uniq[key] = {**u, "count": 1}
        for i, (name, u) in enumerate(uniq.items(), 1):
            suffix = f" ×{u['count']}" if u["count"] > 1 else ""
            t.add_row(str(i), f"{name}{suffix}", f"¥{u['price']:.2f}", u["date"] or "-")
        console.print(t)

    if report.skipped:
        console.print()
        for s in report.skipped:
            console.print(f"  [dim]跳过: {s['name']} — {s['reason']}[/dim]")


async def main():
    parser = argparse.ArgumentParser(description="悠悠有品交易记录导入")
    parser.add_argument("source", choices=["api", "csv", "json"], help="数据来源")
    parser.add_argument("file", nargs="?", help="CSV/JSON 文件路径（source=api 时不需要）")
    parser.add_argument("--dry-run", action="store_true", help="仅预览匹配结果，不写入数据库")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已有的 purchase_price")
    args = parser.parse_args()

    if args.source in ("csv", "json") and not args.file:
        console.print("[red]文件导入需要指定文件路径[/red]")
        sys.exit(1)

    if args.file and not Path(args.file).exists():
        console.print(f"[red]文件不存在: {args.file}[/red]")
        sys.exit(1)

    await init_db()

    console.print(f"[bold]数据来源: {args.source}[/bold]")
    if args.source == "csv":
        records = _parse_csv(args.file)
    elif args.source == "json":
        records = _parse_json(args.file)
    else:
        records = await _fetch_api_records()

    console.print(f"解析到 [cyan]{len(records)}[/cyan] 条购买记录（共 [cyan]{sum(r.quantity for r in records)}[/cyan] 件）")

    if not records:
        console.print("[yellow]无数据可导入[/yellow]")
        return

    report = await do_import(records, dry_run=args.dry_run, overwrite=args.overwrite)
    _print_report(report, args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())
