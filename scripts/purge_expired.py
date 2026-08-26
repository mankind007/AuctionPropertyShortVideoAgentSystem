"""删除过期房源: DB 行 + 对应磁盘 assets 目录 同步清理。

以【执行时刻】的 start_time < now 为准, 可反复运行(管道进行中新过期的会被下次运行捕获)。

用法:
  python scripts/purge_expired.py            # 预览(dry-run), 只打印将删除的内容
  python scripts/purge_expired.py --execute  # 真删
  python scripts/purge_expired.py --execute --grace-hours 24   # 过期超过24小时才删
"""
from __future__ import annotations

import argparse
import datetime
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import config  # noqa: E402
import psycopg2  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="清理过期房源(DB+assets)")
    ap.add_argument("--execute", action="store_true", help="真删(默认只预览)")
    ap.add_argument("--grace-hours", type=int, default=0,
                    help="宽限期: 过期超过 N 小时才删(默认0=立即算过期)")
    args = ap.parse_args()

    cutoff = datetime.datetime.now() - datetime.timedelta(hours=args.grace_hours)
    conn = psycopg2.connect(config.DATABASE_URL.replace("postgresql+psycopg2", "postgresql"))
    cur = conn.cursor()
    cur.execute(
        "select source, item_id, start_time from listings "
        "where start_time is not null and start_time < %s order by source, start_time",
        (cutoff,))
    rows = cur.fetchall()

    by_src: dict[str, int] = {}
    for src, _iid, st in rows:
        by_src[src] = by_src.get(src, 0) + 1
    print(f"过期房源(cutoff={cutoff:%Y-%m-%d %H:%M}): {len(rows)} 套 {by_src}")

    if not args.execute:
        for src, iid, st in rows:
            print(f"  [将删] {src}/{iid}  开拍 {st}")
        print(f"[DRY-RUN] 共 {len(rows)} 行 + assets 目录; 加 --execute 执行")
        return

    removed_dirs = missing_dirs = 0
    for src, iid, _st in rows:
        d = PROJECT_ROOT / "assets" / src / iid
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            removed_dirs += 1
        else:
            missing_dirs += 1
    cur.execute("delete from listings where start_time is not null and start_time < %s", (cutoff,))
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    print(f"[DONE] DB 删除 {deleted} 行; assets 删除目录 {removed_dirs} 个(不存在 {missing_dirs} 个)")


if __name__ == "__main__":
    main()
