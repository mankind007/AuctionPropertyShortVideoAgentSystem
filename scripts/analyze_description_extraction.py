"""全量扫描 DB 中 listings 的 data.description, 评估 extract_description_fields 提取率。

只读不写库; 输出:
  - 控制台摘要(各字段命中率 + 漏提样本数)
  - 临时 CSV: 每条记录的 item_id / description / 提取结果 / 漏提字段

用法:
    $env:PYTHONIOENCODING='utf-8'
    python scripts/analyze_description_extraction.py [--out out.csv] [--limit N]
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db import get_source_data
from utils.description import extract_description_fields

# 已知字段关键词 → (字段键, 正则/子串关键词)
_FIELD_KEYWORDS: dict[str, list[str]] = {
    "房产地址": ["拍卖标的", "位于", "本次拍卖"],
    "建筑面积": ["建筑面积", "建筑总面积", "房屋建筑面积", "房屋面积", "套内面积", "总面积"],
    "总层数": ["总层数", "总楼层", "全部楼层", "房屋总层数"],
    "所在层数": ["所在层数", "所在楼层", "所在层"],
    "朝向": ["朝向"],
    "不动产权证号": ["不动产权证号", "不动产权证书号", "房地产权证号", "产权证号", "不动产权号", "权证号", "产籍号"],
    "房屋类型": ["物业类型", "房屋类型", "规划用途", "设计用途", "房屋用途", "用途"],
    "配套设施": ["配套"],
    "房屋现状": ["房屋现状"],
    "房屋结构": ["房屋结构"],
    "保证金": ["保证金"],
    "增价幅度": ["增价幅度", "加价幅度", "增幅"],
    "抵押信息": ["抵押权人", "抵押", "查封"],
    "优先购买权": ["优先购买权"],
    "租赁情况": ["租赁", "出租"],
    "土地使用年限": ["土地使用年限", "使用年限", "出让年限", "产权年限"],
    "装修情况": ["装修"],
    "户型": ["户型"],
    "土地用途": ["土地用途"],
    "所在区域": ["省", "市", "自治州", "县", "区"],
}


def analyze(source: str, limit: int | None) -> tuple[list[dict], dict[str, dict]]:
    """返回 (记录列表, {字段: {hit, missed, total_words}})。"""
    data = get_source_data(source)
    recs: list[dict] = []
    stats: dict[str, dict] = {k: {"hit": 0, "missed": 0, "word": 0} for k in _FIELD_KEYWORDS}
    n_desc = 0
    for item_id, item in data.items():
        desc = (item.get("data") or {}).get("description")
        if not desc:
            continue
        n_desc += 1
        if limit and n_desc > limit:
            break
        out = extract_description_fields(desc)
        missed = []
        for key, words in _FIELD_KEYWORDS.items():
            present = any(w in desc for w in words)
            if not present:
                continue
            stats[key]["word"] += 1
            if key in out:
                stats[key]["hit"] += 1
            else:
                stats[key]["missed"] += 1
                if key not in missed:
                    missed.append(key)
        recs.append({
            "source": source,
            "item_id": item_id,
            "title": (item.get("title") or "")[:40],
            "description": desc,
            "extracted": " | ".join(f"{k}={v}" for k, v in out.items()),
            "missed": ",".join(missed),
        })
    return recs, stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="", help="CSV 输出路径(默认不写)")
    ap.add_argument("--limit", type=int, default=0, help="每个来源最多分析 N 条(0=全部)")
    args = ap.parse_args()

    all_recs: list[dict] = []
    all_stats: dict[str, dict] = {}
    for src in ("gpai", "ali"):
        recs, stats = analyze(src, args.limit or None)
        all_recs += recs
        for k, v in stats.items():
            all_stats.setdefault(k, {"hit": 0, "missed": 0, "word": 0})
            for kk in ("hit", "missed", "word"):
                all_stats[k][kk] += v[kk]

    print("=== 字段提取率(文本中出现该字段词的记录里, 实际提取到多少) ===", flush=True)
    print(f"{'字段':<8} {'出现':>5} {'提取':>5} {'漏提':>5} {'提取率':>7}", flush=True)
    for k, v in all_stats.items():
        if v["word"] == 0:
            continue
        rate = v["hit"] / v["word"] * 100 if v["word"] else 0
        print(f"{k:<8} {v['word']:>5} {v['hit']:>5} {v['missed']:>5} {rate:>6.1f}%", flush=True)

    missed_recs = [r for r in all_recs if r["missed"]]
    print(f"\n共分析 {len(all_recs)} 条(有 description); {len(missed_recs)} 条存在漏提", flush=True)
    for r in missed_recs[:30]:
        print(f"  [{r['source']} {r['item_id']}] 漏: {r['missed']} | {r['description'][:70]}", flush=True)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with io.open(out_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["source", "item_id", "title", "description",
                                              "extracted", "missed"])
            w.writeheader()
            for r in all_recs:
                row = dict(r)
                row["title"] = r["title"]
                row["description"] = r["description"][:200]
                row["extracted"] = r["extracted"][:200]
                w.writerow(row)
        print(f"\nCSV 已写入: {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())