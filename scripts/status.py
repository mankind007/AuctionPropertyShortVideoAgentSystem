"""打印管线进度: 各阶段完成数(话术/海报/视频/配音/带配音视频)。

用法: python scripts/status.py [--watch] [--interval 60]
  --watch: 每 N 秒刷新一次(运行时盯着进度用)。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import config  # noqa: E402
import psycopg2  # noqa: E402

STAGES = ["script", "script_images", "video", "voice", "video_voiced"]


def snapshot() -> str:
    conn = psycopg2.connect(config.DATABASE_URL.replace("postgresql+psycopg2", "postgresql"))
    cur = conn.cursor()
    cur.execute("select count(*) from listings")
    total = cur.fetchone()[0]
    counts = {}
    for st in STAGES:
        cur.execute(
            "select source, count(*) from listings where data->%s is not null group by source", (st,))
        counts[st] = dict(cur.fetchall())
    conn.close()

    lines = [f"总房源: {total}"]
    for src in ("gpai", "ali"):
        lines.append(f"\n[{src}]")
        for st in STAGES:
            done = counts[st].get(src, 0)
            lines.append(f"  {st:<15} {done}")
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="管线进度")
    ap.add_argument("--watch", action="store_true", help="持续刷新")
    ap.add_argument("--interval", type=int, default=60)
    args = ap.parse_args()

    if not args.watch:
        print(snapshot())
    else:
        try:
            while True:
                print("\033c" + snapshot(), flush=True)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n退出")
