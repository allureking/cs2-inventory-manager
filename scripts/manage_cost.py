#!/usr/bin/env python3
"""
手动成本录入 CLI — 查看/录入/批量导入 inventory_item 的购入价格

用法:
  python scripts/manage_cost.py list                  # 列出无成本记录的饰品
  python scripts/manage_cost.py list --all            # 列出所有饰品（含已有成本）
  python scripts/manage_cost.py set <hash_name> 1500  # 按 market_hash_name 设置价格
  python scripts/manage_cost.py set-id <id> 1500      # 按 DB id 设置价格
  python scripts/manage_cost.py batch costs.csv       # 从 CSV 批量录入
  python scripts/manage_cost.py stats                 # 成本覆盖率统计
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import asyncio
import csv
import logging
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from sqlalchemy import case, func, select, or_

from app.core.constants import ACTIVE_STATUSES
from app.core.database import AsyncSessionLocal, init_db
from app.models.db_models import InventoryItem

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
console = Console()


async def cmd_list(show_all: bool = False, sort_by: str = "name", limit: int = 200):
    """列出库存饰品及其成本状态"""
    async with AsyncSessionLocal() as db:
        query = (
            select(
                InventoryItem.market_hash_name,
                func.count().label("qty"),
                func.sum(
                    func.coalesce(InventoryItem.purchase_price_manual, InventoryItem.purchase_price)
                ).label("total_cost"),
                func.sum(
                    case(
                        (or_(InventoryItem.purchase_price.isnot(None), InventoryItem.purchase_price_manual.isnot(None)), 1),
                        else_=0,
                    )
                ).label("has_cost"),
                func.min(InventoryItem.id).label("min_id"),
            )
            .where(InventoryItem.status.in_(ACTIVE_STATUSES))
            .group_by(InventoryItem.market_hash_name)
        )

        if not show_all:
            query = query.having(
                func.sum(
                    case(
                        (or_(InventoryItem.purchase_price.isnot(None), InventoryItem.purchase_price_manual.isnot(None)), 1),
                        else_=0,
                    )
                ) < func.count()
            )

        if sort_by == "qty":
            query = query.order_by(func.count().desc())
        elif sort_by == "cost":
            query = query.order_by(
                func.sum(func.coalesce(InventoryItem.purchase_price_manual, InventoryItem.purchase_price)).desc().nulls_last()
            )
        else:
            query = query.order_by(InventoryItem.market_hash_name)

        rows = (await db.execute(query)).all()

    title = "所有活跃库存" if show_all else "缺少成本记录的饰品"
    t = Table(title=title, show_lines=False, box=box.SIMPLE_HEAD)
    t.add_column("#", justify="right", style="dim")
    t.add_column("饰品名 (market_hash_name)", max_width=55)
    t.add_column("数量", justify="right")
    t.add_column("有成本", justify="right")
    t.add_column("缺成本", justify="right", style="red")
    t.add_column("单价", justify="right", style="cyan")
    t.add_column("min_id", justify="right", style="dim")

    total_items = 0
    total_missing = 0
    for i, row in enumerate(rows[:limit], 1):
        name, qty, total_cost, has_cost, min_id = row
        missing = qty - has_cost
        avg_price = f"¥{total_cost / has_cost:.0f}" if has_cost and total_cost else "-"
        style = "" if has_cost == qty else "bold"
        t.add_row(str(i), name, str(qty), str(has_cost), str(missing), avg_price, str(min_id), style=style)
        total_items += qty
        total_missing += missing

    console.print(t)
    if len(rows) > limit:
        console.print(f"  [dim]... 还有 {len(rows) - limit} 种饰品未显示[/dim]")
    console.print(f"\n  总计 [cyan]{len(rows)}[/cyan] 种 / [cyan]{total_items}[/cyan] 件，缺成本 [red]{total_missing}[/red] 件")


async def cmd_set(identifier: str, price: float, by_id: bool = False, date: str = "", platform: str = "MANUAL"):
    """设置单个饰品的购入价"""
    async with AsyncSessionLocal() as db:
        if by_id:
            try:
                item_id = int(identifier)
            except ValueError:
                console.print(f"[red]无效 ID: {identifier}[/red]")
                return
            result = await db.execute(
                select(InventoryItem).where(InventoryItem.id == item_id)
            )
            items = list(result.scalars().all())
        else:
            result = await db.execute(
                select(InventoryItem).where(
                    InventoryItem.market_hash_name == identifier,
                    InventoryItem.status.in_(ACTIVE_STATUSES),
                    InventoryItem.purchase_price_manual.is_(None),
                    InventoryItem.purchase_price.is_(None),
                )
            )
            items = list(result.scalars().all())

        if not items:
            console.print(f"[red]未找到匹配的库存: {identifier}[/red]")
            return

        for item in items:
            item.purchase_price_manual = price
            if date:
                item.purchase_date = date
            item.purchase_platform = platform

        await db.commit()

        name = items[0].market_hash_name
        console.print(f"[green]已设置 {len(items)} 件 [bold]{name}[/bold] 的手动成本为 ¥{price:.2f}[/green]")


async def cmd_batch(csv_path: str):
    """
    从 CSV 批量录入成本。CSV 格式:
      market_hash_name,price[,date,platform]
    """
    if not Path(csv_path).exists():
        console.print(f"[red]文件不存在: {csv_path}[/red]")
        return

    records = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (row.get("market_hash_name") or row.get("marketHashName") or row.get("name") or "").strip()
            price_str = (row.get("price") or row.get("purchase_price") or "").strip()
            date = (row.get("date") or row.get("purchase_date") or "").strip()
            platform = (row.get("platform") or "MANUAL").strip()
            if not name or not price_str:
                continue
            try:
                price = float(price_str)
            except ValueError:
                continue
            records.append({"name": name, "price": price, "date": date, "platform": platform})

    console.print(f"解析到 [cyan]{len(records)}[/cyan] 条成本记录")
    if not records:
        return

    updated = 0
    not_found = []
    async with AsyncSessionLocal() as db:
        for rec in records:
            result = await db.execute(
                select(InventoryItem).where(
                    InventoryItem.market_hash_name == rec["name"],
                    InventoryItem.status.in_(ACTIVE_STATUSES),
                    InventoryItem.purchase_price_manual.is_(None),
                    InventoryItem.purchase_price.is_(None),
                )
            )
            items = list(result.scalars().all())

            if not items:
                not_found.append(rec["name"])
                continue

            for item in items:
                item.purchase_price_manual = rec["price"]
                if rec["date"]:
                    item.purchase_date = rec["date"]
                item.purchase_platform = rec["platform"]
                updated += 1

        await db.commit()

    console.print(f"[green]成功更新 {updated} 件饰品的成本[/green]")
    if not_found:
        console.print(f"[yellow]未找到: {', '.join(not_found[:20])}[/yellow]")


async def cmd_stats():
    """成本覆盖率统计"""
    async with AsyncSessionLocal() as db:
        total_r = await db.execute(
            select(func.count()).where(InventoryItem.status.in_(ACTIVE_STATUSES))
        )
        total = total_r.scalar() or 0

        with_cost_r = await db.execute(
            select(func.count()).where(
                InventoryItem.status.in_(ACTIVE_STATUSES),
                or_(InventoryItem.purchase_price.isnot(None), InventoryItem.purchase_price_manual.isnot(None)),
            )
        )
        with_cost = with_cost_r.scalar() or 0

        total_cost_r = await db.execute(
            select(
                func.sum(func.coalesce(InventoryItem.purchase_price_manual, InventoryItem.purchase_price)),
            ).where(
                InventoryItem.status.in_(ACTIVE_STATUSES),
                or_(InventoryItem.purchase_price.isnot(None), InventoryItem.purchase_price_manual.isnot(None)),
            )
        )
        total_cost = total_cost_r.scalar() or 0

        # By status
        status_r = await db.execute(
            select(
                InventoryItem.status,
                func.count().label("total"),
                func.sum(
                    case(
                        (or_(InventoryItem.purchase_price.isnot(None), InventoryItem.purchase_price_manual.isnot(None)), 1),
                        else_=0,
                    )
                ).label("has_cost"),
            )
            .where(InventoryItem.status.in_(ACTIVE_STATUSES))
            .group_by(InventoryItem.status)
        )
        status_rows = status_r.all()

        # By platform
        platform_r = await db.execute(
            select(
                InventoryItem.purchase_platform,
                func.count().label("cnt"),
                func.sum(func.coalesce(InventoryItem.purchase_price_manual, InventoryItem.purchase_price)).label("total"),
            )
            .where(
                InventoryItem.status.in_(ACTIVE_STATUSES),
                or_(InventoryItem.purchase_price.isnot(None), InventoryItem.purchase_price_manual.isnot(None)),
            )
            .group_by(InventoryItem.purchase_platform)
        )
        platform_rows = platform_r.all()

    pct = with_cost / total * 100 if total else 0

    console.print()
    p = Panel(
        f"总库存: [cyan]{total}[/cyan] 件\n"
        f"有成本: [green]{with_cost}[/green] 件 ({pct:.1f}%)\n"
        f"无成本: [red]{total - with_cost}[/red] 件\n"
        f"总成本: [cyan]¥{total_cost:,.0f}[/cyan]\n"
        f"均价: [cyan]¥{total_cost / with_cost:,.0f}[/cyan]" if with_cost else "",
        title="成本覆盖率",
    )
    console.print(p)

    if status_rows:
        t = Table(title="按状态", show_lines=False, box=box.SIMPLE_HEAD)
        t.add_column("状态")
        t.add_column("总数", justify="right")
        t.add_column("有成本", justify="right", style="green")
        t.add_column("覆盖率", justify="right")
        for row in status_rows:
            status, cnt, has = row
            r = f"{has / cnt * 100:.0f}%" if cnt else "0%"
            t.add_row(status, str(cnt), str(has), r)
        console.print(t)

    if platform_rows:
        console.print()
        t = Table(title="按来源平台", show_lines=False, box=box.SIMPLE_HEAD)
        t.add_column("平台")
        t.add_column("件数", justify="right")
        t.add_column("总成本", justify="right", style="cyan")
        for row in platform_rows:
            plat, cnt, tot = row
            t.add_row(plat or "-", str(cnt), f"¥{tot:,.0f}" if tot else "-")
        console.print(t)


async def main():
    parser = argparse.ArgumentParser(description="手动成本录入 CLI")
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="列出饰品及成本状态")
    p_list.add_argument("--all", action="store_true", help="显示所有（含已有成本的）")
    p_list.add_argument("--sort", choices=["name", "qty", "cost"], default="name")
    p_list.add_argument("--limit", type=int, default=200)

    p_set = sub.add_parser("set", help="按 market_hash_name 设置购入价")
    p_set.add_argument("name", help="market_hash_name（精确匹配）")
    p_set.add_argument("price", type=float, help="购入单价（元）")
    p_set.add_argument("--date", default="", help="购入日期 YYYY-MM-DD")
    p_set.add_argument("--platform", default="MANUAL")

    p_id = sub.add_parser("set-id", help="按 DB id 设置购入价")
    p_id.add_argument("id", help="inventory_item.id")
    p_id.add_argument("price", type=float, help="购入单价（元）")
    p_id.add_argument("--date", default="", help="购入日期 YYYY-MM-DD")

    p_batch = sub.add_parser("batch", help="从 CSV 批量录入")
    p_batch.add_argument("file", help="CSV 文件路径")

    p_stats = sub.add_parser("stats", help="成本覆盖率统计")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    await init_db()

    if args.command == "list":
        await cmd_list(show_all=args.all, sort_by=args.sort, limit=args.limit)
    elif args.command == "set":
        await cmd_set(args.name, args.price, date=args.date, platform=args.platform)
    elif args.command == "set-id":
        await cmd_set(args.id, args.price, by_id=True, date=args.date)
    elif args.command == "batch":
        await cmd_batch(args.file)
    elif args.command == "stats":
        await cmd_stats()


if __name__ == "__main__":
    asyncio.run(main())
