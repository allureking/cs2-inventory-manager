#!/usr/bin/env python3
"""
利润监控终端仪表盘 — 持仓总览、盈亏排行、信号高亮

用法:
  python scripts/dashboard.py                  # 单次快照
  python scripts/dashboard.py --watch          # 持续刷新（每60秒）
  python scripts/dashboard.py --watch -i 30    # 每30秒刷新
  python scripts/dashboard.py --top 50         # 显示前50
  python scripts/dashboard.py --sort pnl_pct   # 按利润率排序
  python scripts/dashboard.py --losers         # 只看亏损
  python scripts/dashboard.py --signals        # 只看有信号的
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import argparse
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich import box
from sqlalchemy import case, func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import ACTIVE_STATUSES
from app.core.database import AsyncSessionLocal, init_db
from app.models.db_models import InventoryItem
from app.services.pricing import get_all_latest_prices

logging.basicConfig(level=logging.WARNING)
console = Console()




async def build_dashboard(
    top: int = 30,
    sort_by: str = "pnl_pct",
    losers_only: bool = False,
    signals_only: bool = False,
) -> list:
    """Returns [summary_panel, items_table, signals_table]"""
    renderables = []

    async with AsyncSessionLocal() as db:
        prices = await get_all_latest_prices(db)

        result = await db.execute(
            select(
                InventoryItem.market_hash_name,
                func.count().label("qty"),
                func.sum(func.coalesce(InventoryItem.purchase_price_manual, InventoryItem.purchase_price)).label("total_cost"),
                func.sum(
                    case(
                        (or_(InventoryItem.purchase_price.isnot(None), InventoryItem.purchase_price_manual.isnot(None)), 1),
                        else_=0,
                    )
                ).label("costed_qty"),
                func.avg(func.coalesce(InventoryItem.purchase_price_manual, InventoryItem.purchase_price)).label("avg_cost"),
            )
            .where(InventoryItem.status.in_(ACTIVE_STATUSES))
            .group_by(InventoryItem.market_hash_name)
        )
        rows = result.all()

        items = []
        portfolio_cost = 0.0
        portfolio_value = 0.0
        total_items = 0
        costed_items = 0

        for row in rows:
            name, qty, total_cost, costed, avg_cost = row
            current_price = prices.get(name)
            total_items += qty
            costed_items += costed or 0

            if total_cost and costed:
                avg_c = total_cost / costed
            else:
                avg_c = None

            market_val = current_price * qty if current_price else None
            cost_val = total_cost or 0

            if avg_c and current_price:
                pnl_pct = (current_price - avg_c) / avg_c * 100
                pnl_abs = (current_price - avg_c) * (costed or qty)
            else:
                pnl_pct = None
                pnl_abs = None

            portfolio_cost += cost_val
            if market_val:
                portfolio_value += market_val

            items.append({
                "name": name,
                "qty": qty,
                "costed": costed or 0,
                "avg_cost": avg_c,
                "current_price": current_price,
                "market_value": market_val,
                "total_cost": cost_val,
                "pnl_pct": pnl_pct,
                "pnl_abs": pnl_abs,
            })

        # Filters
        if losers_only:
            items = [i for i in items if i["pnl_pct"] is not None and i["pnl_pct"] < 0]
        if signals_only:
            items = [i for i in items if i["pnl_pct"] is not None and (i["pnl_pct"] > 50 or i["pnl_pct"] < -20)]

        # Sort
        def _sort_key(item):
            v = item.get(sort_by)
            if v is None:
                return -999999 if "desc" not in sort_by else 999999
            return v

        reverse = sort_by in ("pnl_pct", "pnl_abs", "market_value", "qty")
        items.sort(key=_sort_key, reverse=reverse)

        # Summary panel
        total_pnl = portfolio_value - portfolio_cost
        total_pnl_pct = (total_pnl / portfolio_cost * 100) if portfolio_cost > 0 else 0
        pnl_color = "green" if total_pnl >= 0 else "red"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        summary_text = (
            f"[dim]{now_str}[/dim]\n\n"
            f"持仓件数: [cyan]{total_items:,}[/cyan] 件 (有成本 {costed_items:,})\n"
            f"总成本:   [cyan]¥{portfolio_cost:,.0f}[/cyan]\n"
            f"总市值:   [cyan]¥{portfolio_value:,.0f}[/cyan]\n"
            f"总利润:   [{pnl_color}]¥{total_pnl:+,.0f}[/{pnl_color}]\n"
            f"总利润率: [{pnl_color}]{total_pnl_pct:+.2f}%[/{pnl_color}]"
        )
        renderables.append(Panel(summary_text, title="持仓总览", border_style="cyan"))

        # Items table
        t = Table(title=f"饰品盈亏排行 (Top {min(top, len(items))})", show_lines=False, box=box.SIMPLE_HEAD)
        t.add_column("#", justify="right", style="dim", width=4)
        t.add_column("饰品名", no_wrap=True, max_width=50)
        t.add_column("数量", justify="right", width=5)
        t.add_column("均价", justify="right", width=9)
        t.add_column("现价", justify="right", width=9)
        t.add_column("利润率", justify="right", width=9)
        t.add_column("利润额", justify="right", width=11)
        t.add_column("信号", width=6)

        for i, item in enumerate(items[:top], 1):
            pnl_str = f"{item['pnl_pct']:+.1f}%" if item["pnl_pct"] is not None else "-"
            pnl_abs_str = f"¥{item['pnl_abs']:+,.0f}" if item["pnl_abs"] is not None else "-"
            avg_str = f"¥{item['avg_cost']:,.0f}" if item["avg_cost"] else "-"
            cur_str = f"¥{item['current_price']:,.0f}" if item["current_price"] else "-"

            # Color coding
            if item["pnl_pct"] is not None:
                if item["pnl_pct"] > 50:
                    row_style = "bold green"
                elif item["pnl_pct"] > 0:
                    row_style = "green"
                elif item["pnl_pct"] > -10:
                    row_style = "yellow"
                else:
                    row_style = "red"
            else:
                row_style = "dim"

            # Signal flags
            signals = []
            if item["pnl_pct"] is not None:
                if item["pnl_pct"] > 100:
                    signals.append("[bold green]$$[/bold green]")
                elif item["pnl_pct"] > 50:
                    signals.append("[green]$[/green]")
                if item["pnl_pct"] < -20:
                    signals.append("[red]!![/red]")

            signal_str = " ".join(signals) if signals else ""

            t.add_row(str(i), item["name"], str(item["qty"]), avg_str, cur_str,
                       pnl_str, pnl_abs_str, signal_str, style=row_style)

        renderables.append(t)

        # Signal summary
        high_profit = [i for i in items if i["pnl_pct"] is not None and i["pnl_pct"] > 50]
        deep_loss = [i for i in items if i["pnl_pct"] is not None and i["pnl_pct"] < -20]

        if high_profit or deep_loss:
            st = Table(title="信号摘要", show_lines=False, box=box.SIMPLE_HEAD)
            st.add_column("类型", width=12)
            st.add_column("饰品名", max_width=50)
            st.add_column("利润率", justify="right", width=10)
            st.add_column("市值", justify="right", width=12)

            for item in sorted(high_profit, key=lambda x: -(x["pnl_pct"] or 0))[:10]:
                st.add_row(
                    "[green]盈利>50%[/green]",
                    item["name"],
                    f"{item['pnl_pct']:+.1f}%",
                    f"¥{item['market_value']:,.0f}" if item["market_value"] else "-",
                    style="green",
                )
            for item in sorted(deep_loss, key=lambda x: x["pnl_pct"] or 0)[:10]:
                st.add_row(
                    "[red]亏损>20%[/red]",
                    item["name"],
                    f"{item['pnl_pct']:+.1f}%",
                    f"¥{item['market_value']:,.0f}" if item["market_value"] else "-",
                    style="red",
                )
            renderables.append(st)

    return renderables


async def run_once(args):
    await init_db()
    panels = await build_dashboard(
        top=args.top,
        sort_by=args.sort,
        losers_only=args.losers,
        signals_only=args.signals,
    )
    for p in panels:
        console.print(p)


async def run_watch(args):
    await init_db()
    with Live(console=console, refresh_per_second=1) as live:
        while True:
            try:
                panels = await build_dashboard(
                    top=args.top,
                    sort_by=args.sort,
                    losers_only=args.losers,
                    signals_only=args.signals,
                )
                from rich.console import Group
                live.update(Group(*panels))
            except Exception as e:
                live.update(Panel(f"[red]Error: {e}[/red]"))
            await asyncio.sleep(args.interval)


async def main():
    parser = argparse.ArgumentParser(description="利润监控终端仪表盘")
    parser.add_argument("--watch", action="store_true", help="持续刷新模式")
    parser.add_argument("-i", "--interval", type=int, default=60, help="刷新间隔（秒）")
    parser.add_argument("--top", type=int, default=30, help="显示前N个")
    parser.add_argument("--sort", choices=["pnl_pct", "pnl_abs", "market_value", "qty", "name"],
                        default="pnl_pct", help="排序方式")
    parser.add_argument("--losers", action="store_true", help="只看亏损")
    parser.add_argument("--signals", action="store_true", help="只看有信号的（盈利>50%或亏损>20%）")
    args = parser.parse_args()

    if args.watch:
        await run_watch(args)
    else:
        await run_once(args)


if __name__ == "__main__":
    asyncio.run(main())
