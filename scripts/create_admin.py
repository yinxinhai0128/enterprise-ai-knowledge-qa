#!/usr/bin/env python3
"""初始化第一个管理员账号（直接写入 DB，不通过 API）。

用法：
  python scripts/create_admin.py --username admin --password 强密码 --tenant default
"""
from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

# 让脚本能找到 app 模块
sys.path.insert(0, str(Path(__file__).parent.parent))


async def main() -> int:
    parser = argparse.ArgumentParser(description="创建管理员账号")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--tenant", default="default")
    args = parser.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9._@-]+", args.username):
        print("用户名只能包含字母、数字及 . _ @ -", file=sys.stderr)
        return 1

    if len(args.password) < 8:
        print("密码至少 8 位", file=sys.stderr)
        return 1

    # 延迟导入，保证 sys.path 已设置
    import bcrypt
    from app.core.database import AsyncSessionLocal, init_db
    from app.models.user import User

    def hash_pwd(pwd: str) -> str:
        return bcrypt.hashpw(pwd.encode(), bcrypt.gensalt()).decode()

    await init_db()

    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        existing = (await db.execute(select(User).where(User.username == args.username))).scalar_one_or_none()
        if existing:
            print(f"用户 {args.username!r} 已存在")
            return 1
        user = User(
            username=args.username,
            hashed_password=hash_pwd(args.password),
            tenant_id=args.tenant,
            roles=["admin"],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        print(f"管理员账号已创建：username={args.username!r} tenant={args.tenant!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
