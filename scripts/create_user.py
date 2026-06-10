#!/usr/bin/env python3
"""
创建 / 重置应用登录用户（v0.10.0 用户系统）。

用法：
  # 创建 superadmin，随机密码（只打印一次，请保存）
  python3 scripts/create_user.py --db cs2_inventory.db

  # 忘记密码：重置（旧 session 全部失效）
  python3 scripts/create_user.py --db cs2_inventory.db --reset

  # 自定义用户名/角色/密码
  python3 scripts/create_user.py --db cs2_inventory.db --username king --role admin --password '...'

说明：
  - app_user 表由应用启动时 init_db 创建；表不存在时请先启动一次应用。
  - 重置密码会更新 password_changed_at，所有已登录 session 立即失效。
"""

from __future__ import annotations

import argparse
import secrets
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.auth import hash_password  # noqa: E402 — 与服务端同一哈希实现


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", required=True, help="sqlite 数据库文件路径")
    p.add_argument("--username", default="superadmin")
    p.add_argument("--role", default="super_admin",
                   choices=["super_admin", "admin", "viewer"])
    p.add_argument("--password", default=None, help="不传则生成随机密码并打印一次")
    p.add_argument("--reset", action="store_true", help="用户已存在时重置其密码")
    args = p.parse_args()

    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA busy_timeout = 10000")
    try:
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='app_user'"
        ).fetchone()
        if not table:
            print("错误：app_user 表不存在。请先启动一次应用（init_db 会建表）。", file=sys.stderr)
            return 1

        password = args.password or secrets.token_urlsafe(12)
        pw_hash = hash_password(password)
        now = time.time()

        existing = conn.execute(
            "SELECT id, role FROM app_user WHERE username = ?", (args.username,)
        ).fetchone()

        if existing:
            if not args.reset:
                print(f"错误：用户 {args.username} 已存在。重置密码请加 --reset。", file=sys.stderr)
                return 1
            conn.execute(
                "UPDATE app_user SET password_hash = ?, password_changed_at = ? WHERE username = ?",
                (pw_hash, now, args.username),
            )
            action = "已重置密码（所有旧登录已失效）"
        else:
            conn.execute(
                "INSERT INTO app_user (username, password_hash, role, password_changed_at) "
                "VALUES (?, ?, ?, ?)",
                (args.username, pw_hash, args.role, now),
            )
            action = f"已创建（角色 {args.role}）"
        conn.commit()

        print(f"用户 {args.username} {action}")
        print(f"密码: {password}")
        print("（只显示这一次，请立即保存；登录后可在页面右上角修改）")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
