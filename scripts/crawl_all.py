"""多源并行采集编排(公拍网 + 阿里资产) —— CLI 入口,逻辑在 app/orchestrator.py。

示例:
    python scripts/crawl_all.py --pages 1
    python scripts/crawl_all.py --pages 1 --download --db --skip-complete
    python scripts/crawl_all.py --only gpai --pages 0
    python scripts/crawl_all.py --only ali --ali-category 住宅 商业
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.orchestrator import run_sources


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    parser = argparse.ArgumentParser(description="多源并行采集: 公拍网 + 阿里资产")
    parser.add_argument("--pages", type=int, default=1, help="两源通用页数(默认 1)")
    parser.add_argument("--ali-pages", type=int, default=None, help="阿里专属页数(覆盖 --pages)")
    parser.add_argument("--gpai-pages", type=int, default=None, help="公拍网专属页数(覆盖 --pages)")
    parser.add_argument("--ali-category", type=str, nargs="+", default=None,
                        help="阿里分类(默认 住宅),多个空格分隔")
    parser.add_argument("--download", action="store_true", help="两源都打开子页采图并下载")
    parser.add_argument("--db", action="store_true", help="两源结果 upsert 进 PostgreSQL")
    parser.add_argument("--headless", action="store_true", help="无头模式(默认有头)")
    parser.add_argument("--skip-complete", action="store_true",
                        help="断点续传(以 DB 为准): 已采完图的子页跳过,缺的文件离线补下")
    parser.add_argument("--only", type=str, choices=["gpai", "ali"], default=None,
                        help="只跑单源(默认双源并行)")
    args = parser.parse_args()

    sources = ["gpai", "ali"] if not args.only else [args.only]
    return run_sources(
        sources, pages=args.pages, ali_pages=args.ali_pages, gpai_pages=args.gpai_pages,
        ali_category=args.ali_category, download=args.download, db=args.db,
        headless=args.headless, skip_complete=args.skip_complete,
    )


if __name__ == "__main__":
    sys.exit(main())