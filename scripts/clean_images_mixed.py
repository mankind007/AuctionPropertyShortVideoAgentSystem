"""临时清洗脚本: 剔除 DB listings.data->images 中混入的播放图标并去重。

背景: 阿里资产轮播会把短视频播放图标(imgextra CDN / `tps-72-72.png` 占位图)
混进房源主图, 且同一张图可能被轮播重复引用(下载成两个文件)。

处理(逐条, 幂等):
- 过滤 `_is_icon_image` 判定的图标 URL
- 按 URL 去重, 保留首次出现且 file 非空的条目
- 可选删除因此失引用的本地孤儿文件(assets/ali/{item_id}/imgs/xx.jpg)
- file 文件名保留原名(删除中间项会出现断档如 01,03,04, 不影响下游)

用法:
    python scripts/clean_images_mixed.py [--source ali] [--limit 0] [--remove-files] [--dry-run]
    --dry-run      只统计不动 DB
    --remove-files 同时删除失引用的本地文件(默认仅清理 DB)
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

_ALI = PROJECT_ROOT / "skills" / "ali-assets-crawler" / "scripts" / "crawler.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ALI = _load(_ALI, "ali_crawler")
_is_icon = ALI._is_icon_image

from db import session_scope  # noqa: E402
from sqlalchemy import text  # noqa: E402


def _clean_images(imgs) -> list:
    """返回清洗后的 images 列表(兼容 dict {url,file} 或纯字符串 URL)。"""
    out: list = []
    seen = set()
    for x in imgs or []:
        url = x.get("url") if isinstance(x, dict) else x
        if not url or _is_icon(url) or url in seen:
            continue
        seen.add(url)
        if isinstance(x, dict):
            out.append({"url": url, "file": x.get("file")})
        else:
            out.append(url)
    return out


def _main(source: str, limit: int, remove_files: bool, dry_run: bool) -> int:
    sql = ("SELECT item_id, url, data FROM listings WHERE source=:src "
           "AND data->'images' IS NOT NULL "
           "AND (data::text LIKE '%imgextra%' OR data::text LIKE '%tps-%') "
           "ORDER BY item_id DESC")
    if limit > 0:
        sql += f" LIMIT {limit}"
    total_fixed = total_removed = 0
    with session_scope() as s:
        rows = s.execute(text(sql), {"src": source}).fetchall()
        print(f"[{source}] 命中 {len(rows)} 条含图标/占位的记录", flush=True)
        for item_id, _, data in rows:
            before = (data or {}).get("images") or []
            ori_n = len(before)
            removed = [x for x in before
                       if _is_icon(x.get("url") if isinstance(x, dict) else x)]
            clean = _clean_images(before)
            if len(clean) == ori_n:
                continue
            print(f"  {item_id} 图 {ori_n} → {len(clean)} (去掉图标/占位/重复 "
                  f"{ori_n - len(clean)} 张)", flush=True)
            total_fixed += 1
            total_removed += ori_n - len(clean)
            if remove_files:
                keep_files = {x.get("file") for x in clean if isinstance(x, dict)}
                # 失引用文件 = 不在清洗后 / 被去重掉的, 且本地存在
                drop_file = set()
                for x in before:
                    if not isinstance(x, dict) or not x.get("file"):
                        continue
                    f = x["file"]
                    if f not in keep_files:
                        drop_file.add(f)
                for f in sorted(drop_file):
                    fp = PROJECT_ROOT / "assets" / source / str(item_id) / "imgs" / f
                    if fp.exists():
                        if not dry_run:
                            fp.unlink()
                        print(f"      - 删除本地文件 {f}", flush=True)
                    else:
                        print(f"      - (DB 引用但本地无) {f}", flush=True)
            if not dry_run:
                import json

                new_data = dict(data or {})
                new_data["images"] = clean
                s.execute(
                    text("UPDATE listings SET data=CAST(:data AS jsonb) "
                         "WHERE source=:src AND item_id=:id"),
                    {"data": json.dumps(new_data, ensure_ascii=False),
                     "src": source, "id": item_id},
                )
        print(f"完成: 修正 {total_fixed} 条, 去掉图片 {total_removed} 张"
              + ("(dry-run, 未写库)" if dry_run else ""), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="清洗 data->images 中的播放图标/重复图")
    parser.add_argument("--source", type=str, default="ali", choices=["ali", "gpai"])
    parser.add_argument("--limit", type=int, default=0, help="处理条数上限(0=全部)")
    parser.add_argument("--remove-files", action="store_true", help="同时删除失引用的本地文件")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = parser.parse_args()
    return _main(args.source, args.limit, args.remove_files, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())