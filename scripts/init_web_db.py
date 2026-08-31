"""Web 应用数据库初始化:建表 + 创建初始 admin 用户。

用法:
    python scripts/init_web_db.py

环境变量:
    ADMIN_INIT_PASSWORD (默认 admin666,来自 .env)
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config  # noqa: F401 触发 .env 加载

from db import init_db
from db.models import User, UserRole
from db.db import session_scope
from config import ADMIN_INIT_PASSWORD
from passlib.hash import bcrypt as bcrypt_hash


def main() -> int:
    # 1. 建表(含 db.models 的新表)
    print("正在建表...")
    ok = init_db(create_all=True)
    if not ok:
        print("建表失败,请检查数据库连接和 .env 配置")
        return 1
    print("建表完成")

    # 2. 创建/更新 admin 用户
    with session_scope() as s:
        admin = s.query(User).filter_by(username="admin").first()
        if admin:
            print("admin 用户已存在,更新密码...")
            admin.hashed_password = bcrypt_hash.hash(ADMIN_INIT_PASSWORD)
            admin.role = UserRole.ADMIN
            admin.is_active = True
        else:
            print(f"创建 admin 用户 (密码: {ADMIN_INIT_PASSWORD})")
            admin = User(
                username="admin",
                email=None,
                hashed_password=bcrypt_hash.hash(ADMIN_INIT_PASSWORD),
                role=UserRole.ADMIN,
                is_active=True,
            )
            s.add(admin)
        s.commit()
    print("初始化完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())