"""临时脚本: 清洗 data.description 中的占位文案。

场景: 阿里 susong 模板页面有「标的物属性」(data.property_info) 时,
description 往往仍是「公告详情加载中……」占位(页面无拍卖标的描述)。
既然属性信息已在,该占位描述无意义,本脚本把它从 data 中移除。

规则: description 含「公告详情」或「加载中」(占位文案) 的记录,若 property_info 非空
(非 '', 非 '{}') 则删除 description 字段;否则保留(确无属性时留待 fill 脚本处理)。

用法:
    python scripts/clean_placeholder_desc.py [--dry-run] [--source ali|gpai|all]
  --dry-run: 只统计不写库(默认执行写库)。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def _is_placeholder(desc: str) -> bool:
    return "公告详情" in desc or "加载中" in desc


def main() -> int:
    parser = argparse.ArgumentParser(description="清洗 data.description 占位文案(有属性时)")
    parser.add_argument("--source", default="all", choices=["ali", "gpai", "all"])
    parser.add_argument("--dry-run", action="store_true", default=False)
    args = parser.parse_args()

    from sqlalchemy import text

    from db import session_scope, upsert_listing

    src_cond = "" if args.source == "all" else "AND source=:src"
    params = {"src": args.source} if args.source != "all" else {}
    sql = ("SELECT item_id, source, data FROM listings "
           "WHERE (data->>'description' LIKE '%公告详情%' OR data->>'description' LIKE '%加载中%') "
           f"{src_cond}")
    n_ok = n_keep = 0
    samples = []
    try:
        with session_scope() as s:
            rows = s.execute(text(sql), params).fetchall()
        for item_id, source, data in rows:
            data = dict(data or {})
            desc = data.get("description") or ""
            if not _is_placeholder(desc):
                continue
            prop = data.get("property_info")
            has_prop = bool(prop) and prop not in ("", "{}")
            if not has_prop:
                n_keep += 1
                continue
            data.pop("description", None)
            if not args.dry_run:
                upsert_listing({"source": source, "item_id": item_id, "data": data})
            n_ok += 1
            if len(samples) < 10:
                samples.append(f"{source} {item_id}")
    except Exception as e:  # noqa: BLE001
        print(f"  ! 清洗失败: {e}", flush=True)
        return 1

    verb = "将清洗" if args.dry_run else "已清洗"
    print(f"{verb} {n_ok} 条(占位描述+有属性,删除 description);保留 {n_keep} 条(仅占位描述、无属性,留待 fill)", flush=True)
    for s_ in samples:
        print("  ", s_, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())