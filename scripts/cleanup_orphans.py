"""清理孤儿资产目录: 磁盘 assets/<source>/<item_id> 存在但 DB 无对应行的目录。

用途: 过期清理(purge_expired)删除失败留下的残留、或采集后入库失败的残留。

用法:
  python scripts/cleanup_orphans.py            # 预览
  python scripts/cleanup_orphans.py --execute  # 真删(逐个尝试, 失败会列出原因)
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import config  # noqa: E402
import psycopg2  # noqa: E402


def remove_tree(d: Path) -> tuple[Path | None, Exception | None]:
    """直接整树删除, 瞬时占用靠指数退避重试(0.5→8s); 返回 (残留路径或None, 最后一次异常)。"""
    err: Exception | None = None
    for wait in (0, 0.5, 1, 2, 4, 8):
        if not d.exists():
            return None, None
        try:
            shutil.rmtree(d)
            return None, None
        except Exception as exc:  # noqa: BLE001
            err = exc
            time.sleep(wait)
    return d, err


def main() -> None:
    ap = argparse.ArgumentParser(description="清理磁盘孤儿资产目录")
    ap.add_argument("--execute", action="store_true", help="真删(默认只预览)")
    args = ap.parse_args()

    conn = psycopg2.connect(config.DATABASE_URL.replace("postgresql+psycopg2", "postgresql"))
    cur = conn.cursor()
    cur.execute("select source, item_id from listings")
    db = set(map(tuple, cur.fetchall()))
    conn.close()

    orphans: list[Path] = []
    for src in ("gpai", "ali"):
        base = PROJECT_ROOT / "assets" / src
        if not base.exists():
            continue
        for p in base.iterdir():
            if p.is_dir() and ((src, p.name) not in db or p.name.startswith("_trash_")):
                orphans.append(p)

    print(f"孤儿资产目录(DB 无记录): {len(orphans)} 个")
    if not args.execute:
        for p in sorted(orphans):
            stages = ",".join(x.name for x in p.iterdir() if x.is_dir())
            print(f"  [将删] {p.relative_to(PROJECT_ROOT)}  ({stages or '空'})")
        print("[DRY-RUN] 加 --execute 执行")
        return

    removed = failed = 0
    for p in sorted(orphans):
        leftover, exc = remove_tree(p)
        if leftover is None:
            removed += 1
        else:
            failed += 1
            print(f"  [FAIL] {p.relative_to(PROJECT_ROOT)}: {exc}")
    print(f"[DONE] 删除 {removed} 个, 失败 {failed} 个(残留可下次运行再清)")


if __name__ == "__main__":
    main()
