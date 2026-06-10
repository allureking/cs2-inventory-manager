#!/usr/bin/env python3
"""
恢复 price_history 中被 backfill 合成数据污染的 ALL 行。

背景（docs/architecture-review-2026-06-10.md 提案7）：
  2026-06-08 09:38 触发的 POST /api/analysis/backfill 用均价插值 + ±1.5% 随机噪声
  生成 45 天 ALL 平台合成日线，on_conflict_do_update 覆盖了真实聚合行。
  分平台（BUFF/YOUPIN/STEAM 等）真实行未被触碰，可重放 aggregate_daily 的
  ALL 聚合逻辑（跨平台 MIN open/close、MAX high、MIN low、SUM counts）恢复。

行为：
  - 对窗口内每个 record_date：
      * 有非 0 价分平台行的品种 → 按聚合逻辑重算并覆盖 ALL 行（幂等）；
      * 无任何非 0 价分平台行支撑的 ALL 行 → 无真实数据可恢复，删除。
  - 默认 dry-run 只打印将发生什么；--execute 才真正写库（单事务）。

用法：
  python3 scripts/restore_all_rows.py --db cs2_inventory.db                 # dry-run
  python3 scripts/restore_all_rows.py --db cs2_inventory.db --execute       # 执行
  可选 --start/--end 调整窗口（record_date 格式 YYYYMMDD），
  默认 20260423–20260609 覆盖污染窗口（4/24-6/7）± 1 天时区余量。

  ⚠ 勿把窗口扩到 202602 之前：202601 的 price_history 只有 ALL 行
    （上一代 backfill 的合成数据,无分平台源），扩窗会把 1 月历史整段删除。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys

# aggregate_daily 中 ALL 行的聚合口径（app/services/collector.py），逐字段一致。
# close_price > 0 过滤：停用平台（CSMONEY/DMARKET/SKINPORT/WAXPEER 等）在窗口内
# 写了大量 0 价占位行，不过滤会把恢复出的 ALL 行拖成 0（窗口前历史 64% ALL 行
# 即因此为 0——本脚本顺带把窗口内的这类行也恢复成有意义的跨平台最低价）。
RECOMPUTE_SQL = """
    SELECT market_hash_name,
           MIN(open_price), MIN(close_price),
           MAX(high_price), MIN(low_price),
           SUM(sell_count), SUM(bidding_count)
    FROM price_history
    WHERE record_date = ? AND platform != 'ALL' AND close_price > 0
    GROUP BY market_hash_name
"""

UPSERT_SQL = """
    INSERT INTO price_history
        (market_hash_name, platform, open_price, close_price,
         high_price, low_price, sell_count, bidding_count, record_date)
    VALUES (?, 'ALL', ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(market_hash_name, platform, record_date) DO UPDATE SET
        open_price = excluded.open_price,
        close_price = excluded.close_price,
        high_price = excluded.high_price,
        low_price = excluded.low_price,
        sell_count = excluded.sell_count,
        bidding_count = excluded.bidding_count
"""


def list_dates(conn: sqlite3.Connection, start: str, end: str) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT record_date FROM price_history "
        "WHERE record_date BETWEEN ? AND ? AND platform = 'ALL' "
        "ORDER BY record_date",
        (start, end),
    ).fetchall()
    return [r[0] for r in rows]


def restore(db_path: str, start: str, end: str, execute: bool) -> int:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout = 10000")  # 服务在线时(WAL)避免 database is locked
    try:
        dates = list_dates(conn, start, end)
        if not dates:
            print(f"窗口 {start}–{end} 内没有 ALL 行，无事可做。")
            return 0

        total_upsert = total_delete = total_unchanged = 0
        print(f"{'date':<10} {'重算覆盖':>8} {'已一致':>6} {'删除(无源)':>10}")

        for d in dates:
            recomputed = conn.execute(RECOMPUTE_SQL, (d,)).fetchall()
            recomputed_names = {r[0] for r in recomputed}

            existing = dict(
                conn.execute(
                    "SELECT market_hash_name, open_price || '|' || close_price || '|' "
                    "|| high_price || '|' || low_price "
                    "FROM price_history WHERE record_date = ? AND platform = 'ALL'",
                    (d,),
                ).fetchall()
            )

            # 无任何分平台行支撑的 ALL 行 → 纯合成，删除
            orphans = [n for n in existing if n not in recomputed_names]

            upserts = []
            unchanged = 0
            for r in recomputed:
                name, o, c, h, lo, sc, bc = r
                fp = f"{o}|{c}|{h}|{lo}"
                if existing.get(name) == fp:
                    unchanged += 1
                else:
                    upserts.append((name, o, c, h, lo, sc, bc, d))

            print(f"{d:<10} {len(upserts):>8} {unchanged:>6} {len(orphans):>10}")
            total_upsert += len(upserts)
            total_unchanged += unchanged
            total_delete += len(orphans)

            if execute:
                conn.executemany(UPSERT_SQL, upserts)
                conn.executemany(
                    "DELETE FROM price_history "
                    "WHERE record_date = ? AND platform = 'ALL' AND market_hash_name = ?",
                    [(d, n) for n in orphans],
                )

        print("-" * 40)
        print(f"合计: 重算覆盖 {total_upsert} 行, 已一致 {total_unchanged} 行, "
              f"删除无源合成行 {total_delete} 行")

        if execute:
            conn.commit()
            print("已提交。")
        else:
            print("dry-run（未写库）。加 --execute 执行。")
        return 0
    finally:
        conn.close()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", required=True, help="sqlite 数据库文件路径")
    p.add_argument("--start", default="20260423", help="窗口起始 record_date（含）")
    p.add_argument("--end", default="20260609", help="窗口结束 record_date（含）")
    p.add_argument("--execute", action="store_true", help="真正写库（默认 dry-run）")
    args = p.parse_args()
    return restore(args.db, args.start, args.end, args.execute)


if __name__ == "__main__":
    sys.exit(main())
