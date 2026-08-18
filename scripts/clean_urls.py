"""脚本: 清洗 listings 表中 url 的追踪参数(track_id/spm/utm_* 等)。

列表页抓回的 href 常带 `?track_id=xxxx`,属追踪标志;新采集入口(item_url)已自动剥离,
本脚本仅对历史存量做一次清洗。只更新 url,不动其他字段。

用法:
    python scripts/clean_urls.py [--source ali|gpai|all] [--dry-run]
  --dry-run: 只统计受影响行数,不写库(默认执行写库)。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from utils.parsing import strip_track_params  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="清洗 listings.url 的追踪参数")
    parser.add_argument("--source", default="all", choices=["ali", "gpai", "all"],
                        help="清洗哪个源(默认 all)")
    parser.add_argument("--dry-run", action="store_true", default=False,
                        help="只统计不写库")
    args = parser.parse_args()

    from sqlalchemy import text

    from db import session_scope

    src_cond = "" if args.source == "all" else "AND source=:src"
    params = {"src": args.source} if args.source != "all" else {}
    rows = []
    try:
        with session_scope() as s:
            r = s.execute(text(
                f"SELECT item_id, source, url FROM listings WHERE url LIKE '%?%' {src_cond}"
            ), params).fetchall()
            pending = []
            for item_id, source, url in r:
                cleaned = strip_track_params(url or "")
                if cleaned != url:
                    pending.append((item_id, source, url, cleaned))
            if not args.dry_run and pending:
                for item_id, source, _old, newurl in pending:
                    s.execute(
                        text("UPDATE listings SET url=:u WHERE source=:s AND item_id=:i"),
                        {"u": newurl, "s": source, "i": item_id},
                    )
        n = len(pending)
    except Exception as e:  # noqa: BLE001
        print(f"  ! 清洗失败: {e}", flush=True)
        return 1

    if args.dry_run:
        print(f"[dry-run] 将清洗 {n} 条", flush=True)
    else:
        print(f"清洗完成, 共更新 {n} 条", flush=True)
    for item_id, source, old_url, new_url in pending[:10]:
        print(f"  {source} {item_id}: {old_url}  ->  {new_url}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())