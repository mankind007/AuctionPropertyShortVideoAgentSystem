"""建表脚本 —— 在 PostgreSQL 中创建 listings 表(幂等,DB 已建则跳过)。

前提:
1. 已填写 .env 的 DATABASE_URL(默认 postgresql+psycopg2://postgres:postgres@localhost:5432/auction)
2. 已存在数据库 auction(若未建库,先执行:
   createdb -U postgres auction 或 psql -U postgres -c "CREATE DATABASE auction")

示例:
    python scripts/init_db.py
    python scripts/init_db.py --url postgresql+psycopg2://postgres:密码@localhost:5432/auction
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化法拍房源库表(listings)")
    parser.add_argument("--url", type=str, default="",
                        help="DATABASE_URL(默认读 .env;覆盖传入则优先)")
    args = parser.parse_args()

    if args.url:
        from sqlalchemy import create_engine

        from models.listing import Base

        engine = create_engine(args.url, future=True)
        Base.metadata.create_all(bind=engine)
        engine.dispose()
        print(f"建表完成(URL 参数): {args.url.split('@')[-1]}")
        return 0

    import src.db  # noqa: F401  确保 src 可导入(加载 .env)

    from src.db import DATABASE_URL  # noqa: F401
    from src.config import DATABASE_URL as CFG_URL

    try:
        from src.db import init_db

        ok = init_db(create_all=True)
    except Exception as e:  # noqa: BLE001
        print(f"建表失败: {e}")
        print("请确认: 1) .env 的 DATABASE_URL 已填对 2) 数据库已创建 3) PostgreSQL 已启动")
        return 1
    if not ok:
        print("建表失败(见 src/db.init_db 抛出的原因);请检查 .env 与数据库状态")
        return 1
    print(f"建表完成: {CFG_URL.split('@')[-1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())