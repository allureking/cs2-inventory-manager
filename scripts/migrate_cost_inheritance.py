#!/usr/bin/env python3
"""
成本继承迁移（v0.13.0,提案5①）— 把滞留在 unknown 僵尸行上的购入成本
迁移到同 (hash, abrade) 的无成本活跃行(零歧义:两侧各恰一行才动)。

用法(服务器上,venv 内):
  默认 dry-run,只打印 + 写 CSV 审计,不改库:
    venv/bin/python3 scripts/migrate_cost_inheritance.py --db cs2_inventory.db
  人工抽查 CSV 后执行:
    venv/bin/python3 scripts/migrate_cost_inheritance.py --db cs2_inventory.db --execute

幂等:受赠行获得成本后不再满足"无成本"条件,重跑自然跳过。
"""

import argparse
import asyncio
import csv
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="sqlite 文件路径,如 cs2_inventory.db")
    ap.add_argument("--execute", action="store_true", help="实际写入(默认 dry-run)")
    args = ap.parse_args()

    import os
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{args.db}"
    # 重新加载 settings 之前导入会用旧值;直接构造引擎最稳
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from app.services.cost_inheritance import find_inheritance_pairs, apply_inheritance

    engine = create_async_engine(f"sqlite+aiosqlite:///{args.db}")
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with Session() as db:
        pairs = await find_inheritance_pairs(db)
        total_cost = sum(p.purchase_price for p in pairs)
        print(f"零歧义配对: {len(pairs)} 对,可迁移成本合计 ¥{total_cost:,.2f}")

        csv_path = f"/tmp/cost_inheritance_{datetime.now():%Y%m%d_%H%M%S}.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["active_id", "donor_id", "market_hash_name", "abrade",
                        "purchase_price", "purchase_date", "purchase_platform"])
            for p in pairs:
                w.writerow(list(p))
        print(f"审计 CSV: {csv_path}")

        if not args.execute:
            print("dry-run 结束(未写库)。确认 CSV 后加 --execute 执行。")
            return

        applied = await apply_inheritance(db, pairs)
        print(f"已执行: {applied} 行获得成本。")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
