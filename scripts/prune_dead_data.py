#!/usr/bin/env python3
"""
死数据归档清理（v0.13.0,提案8）。

清理对象(全部先归档后删,归档=执行前 VACUUM INTO 的完整紧凑快照):
  1. item            — 39k 行只有 ~350 行被引用(csqaq 映射 / 持仓名)。其余为
                       全量饰品字典,从未被查询路径使用 → 删未引用行
  2. item_avg_price  — 只写不读(fetch_avg_price 写入后无任何消费方)→ 清空
  3. price_history   — 7 个停用平台 ~141k 行(白名单 YOUPIN,BUFF,STEAM + ALL)→ 删
                       ⚠ 红线:绝不动 ALL 行(202601 只有 ALL,删了 1 月历史消失)
  4. quant_alert     — 60 天前的告警(99.9% 未读噪音)→ 删;credential 类永远保留
  5. portfolio_snapshot — 30 天前降采样为日粒度(每日保留最后一条)

用法(服务器,先停不需要;DELETE 都带 busy_timeout):
  dry-run: venv/bin/python3 scripts/prune_dead_data.py --db cs2_inventory.db
  执行:    venv/bin/python3 scripts/prune_dead_data.py --db cs2_inventory.db --execute
执行流程:VACUUM INTO 归档 → DELETE → VACUUM 回收。
"""

import argparse
import sqlite3
from datetime import datetime
from pathlib import Path

STMTS = [
    ("item 未引用行", """
        DELETE FROM item WHERE csqaq_good_id IS NULL
          AND market_hash_name NOT IN (SELECT DISTINCT market_hash_name FROM inventory_item)
    """),
    ("item_avg_price 全部(只写不读)", "DELETE FROM item_avg_price"),
    ("price_history 停用平台", """
        DELETE FROM price_history WHERE platform NOT IN ('ALL','BUFF','YOUPIN','STEAM')
    """),
    ("quant_alert 60天前(credential 保留)", """
        DELETE FROM quant_alert WHERE created_at < datetime('now','-60 day')
          AND alert_type != 'credential'
    """),
    ("portfolio_snapshot 30天前非日末行", """
        DELETE FROM portfolio_snapshot WHERE substr(snapshot_minute,1,8) < strftime('%Y%m%d','now','-30 day')
          AND snapshot_minute NOT IN (
            SELECT MAX(snapshot_minute) FROM portfolio_snapshot GROUP BY substr(snapshot_minute,1,8)
          )
    """),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    db = sqlite3.connect(args.db)
    db.execute("PRAGMA busy_timeout=10000")

    print("== 规模预估 ==")
    for label, stmt in STMTS:
        count_sql = "SELECT COUNT(*) FROM (" + stmt.strip().replace("DELETE FROM", "SELECT 1 FROM", 1) + ")"
        n = db.execute(count_sql).fetchone()[0]
        print(f"  {label:42s} {n:>8,} 行")

    if not args.execute:
        print("dry-run 结束(未删除)。加 --execute 执行(自动先归档快照)。")
        return

    archive_dir = Path(args.db).resolve().parent / "archive"
    archive_dir.mkdir(exist_ok=True)
    snap = archive_dir / f"pre_prune_{datetime.now():%Y%m%d_%H%M%S}.db"
    print(f"== 归档快照 → {snap} ==")
    db.execute(f"VACUUM INTO '{snap}'")

    print("== 执行删除 ==")
    total = 0
    for label, stmt in STMTS:
        cur = db.execute(stmt)
        print(f"  {label:42s} -{cur.rowcount:,}")
        total += cur.rowcount
    db.commit()

    print("== VACUUM 回收 ==")
    db.execute("VACUUM")
    size_mb = Path(args.db).stat().st_size / 1024 / 1024
    print(f"完成:删除 {total:,} 行,DB 现 {size_mb:.0f} MB;归档 {snap}")


if __name__ == "__main__":
    main()
