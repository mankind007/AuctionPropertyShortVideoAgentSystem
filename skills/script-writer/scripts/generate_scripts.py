"""script-writer: 法拍房话术(口播稿)生成。

从 DB 取房源字段 + assets/短视频宣传话术.csv 素材库 → 规则填充生成 8 角度话术,
可选 --llm 调 agent/model.py 基座润色增强 → 校验回退 → 写回 DB data.script。

话术与海报职责分离: 本脚本只出 data.script; 海报合成由 promo-image 读稿完成。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import csv
import random
import re
from typing import Dict, List, Optional

import config

CSV_PATH = PROJECT_ROOT / "assets" / "短视频宣传话术.csv"

# 角度逻辑顺序(决定话术输出顺序, 与 promo-image 海报推进一致)
ANGLE_ORDER = [
    "开场钩子", "房源硬指标", "价格解析", "地段与配套",
    "常见误区", "风险提示", "紧迫感", "行动号召",
]

# property_info 候选键(与旧 compose.py 同源迁出)
FIELD_KEYS: Dict[str, List[str]] = {
    "小区名称": ["小区名称", "标的物名称", "拍品名称", "项目名称", "标的名称"],
    "坐落": ["坐落"],
    "建筑面积": ["建筑面积_合计", "建筑面积", "建筑总面积", "房屋建筑面积", "套内面积", "总面积"],
    "户型": ["户型", "房屋户型"],
    "朝向": ["朝向", "房屋朝向"],
    "所在楼层": ["所在楼层", "房屋楼层"],
    "总层数": ["总层数", "总楼层"],
    "装修": ["装修情况", "装修程度"],
    "房龄": ["房产年龄"],
    "房屋用途": ["房屋用途", "用途", "房屋规划用途"],
    "建筑结构": ["建筑结构", "房屋结构"],
    "权利限制": ["权利限制情况", "抵押情况", "查封情况", "权利限制情况及瑕疵情况"],
    "税费": ["税费负担", "税、费承担", "税费情况"],
    "腾空交付": ["是否已腾空", "腾空情况", "占用情况", "居住情况"],
    "周边配套": ["周边配套"],
    "保证金": ["保证金", "保证金和增价幅度"],
    "增价幅度": ["增价幅度", "加价幅度"],
}


# ─── 工具函数 ───

def _get_prop(info: dict, keys: list[str], default: str = "") -> str:
    """从 property_info 按候选键取第一个非空值。"""
    for k in keys:
        v = info.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return default


def _clean_title(t: str) -> str:
    """清理标题: 去掉拍次标签(【一拍】等)、括号注释(〔权证号…〕)、"位于/坐落于"等前缀。"""
    if not t:
        return ""
    t = re.sub(r"^【(一拍|二拍|三拍|变卖|第一次|第二次)】", "", t.strip())
    t = re.sub(r"^(位于|坐落于|地址[：:]?|标的物地址[：:]?)", "", t)
    t = re.sub(r"\d{6,}(?:\.\d+)?\s*㎡", "", t)
    t = re.sub(r"[\[【〔][^\]】〕]*[\]】〕]", "", t)
    t = re.sub(r"[\[【〔].*$", "", t)
    t = re.sub(r"^[\]】〕].*$", "", t)
    return t.strip()


_REGION_BLACKLIST = ("开发", "高新", "工业", "园区", "新区", "保税", "示范")


def _extract_region(text: str) -> str:
    """从地址提取「XX市/区/县」; 黑名单过滤「开发区/高新区」等误判。"""
    if not text:
        return ""
    for m in re.finditer(r"([\u4e00-\u9fff]{2,4}?)(市|区|县)", text):
        cand = m.group(1) + m.group(2)
        if any(b in cand for b in _REGION_BLACKLIST):
            continue
        return cand
    return ""


def _clean_zuoluo(v) -> str:
    """清洗坐落: 剥离各类括号注释(含未闭合的【〔[ → 直接截断), 过滤源数据残句/垃圾值。"""
    if not v:
        return ""
    s = str(v).strip()
    s = re.sub(r"[\[【〔][^\]】〕]*[\]】〕]", "", s)
    s = re.sub(r"[\[【〔].*$", "", s)
    s = re.sub(r"^[\]】〕].*$", "", s)
    s = re.sub(r"、([^、]{1,8})$", lambda m: (m.group(0) if not re.search(r"市|区|县", m.group(1)) else ""), s)
    s = s.strip()
    if len(s) < 4:
        return ""
    if any(k in s for k in ("信息更新", "详见", "以实际", "以现场", "为准", "请自行", "咨询", "调查情况")):
        return ""
    return s


def _amount_to_wan(v) -> str:
    """金额字符串统一转为「万元」数字(不带单位)。"""
    if not v:
        return ""
    m = re.search(r"([\d.]+)\s*(万|元)?", str(v))
    if not m:
        return ""
    num = float(m.group(1))
    unit = m.group(2) or ""
    if unit == "万":
        val = num
    elif unit == "元" or num >= 1000:
        val = num / 10000
    else:
        val = num
    s = f"{val:.4f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _fmt_num(v: float, nd: int = 2) -> str:
    """浮点数转字符串: 去掉多余尾随 0 与小数点(整数直接显示整数)。

    如 121.80 → "121.8", 398.00 → "398", 7.0 → "7", 7.05 → "7.05"。
    """
    s = f"{v:.{nd}f}".rstrip("0").rstrip(".")
    return s if s else "0"


_PUNCT = "，。、；：！？…—·"


def _clean_text(s: str) -> str:
    """清理填充后文本: 合并连续标点、去行首/句尾残标点、去空格。"""
    out: list[str] = []
    for ch in s:
        if ch in _PUNCT and out and out[-1] in _PUNCT:
            continue
        out.append(ch)
    s = "".join(out)
    s = re.sub(r"\s+", "", s).strip()
    while s and s[0] in _PUNCT:
        s = s[1:].strip()
    while s and s[-1] in "，、；：":
        s = s[:-1].strip()
    return s


# ─── 字段提取 ───

def extract_fields(data: dict, title: str) -> dict[str, str]:
    """从房源 data + title 提取所有模板填充字段(含派生)。"""
    pi: dict = data.get("property_info", {}) or {}
    f: dict[str, str] = {}

    clean_title = _clean_title(title)
    f["标题"] = title or ""
    f["小区名称"] = _clean_title(
        _get_prop(pi, FIELD_KEYS["小区名称"], default=clean_title))

    raw_zuoluo = _get_prop(pi, FIELD_KEYS["坐落"])
    f["区域"] = _extract_region(clean_title) or _extract_region(raw_zuoluo)
    f["坐落"] = _clean_zuoluo(raw_zuoluo)

    for field, keys in FIELD_KEYS.items():
        if field not in f:
            f[field] = _get_prop(pi, keys)

    for k in ["保证金", "增价幅度"]:
        f[k] = _amount_to_wan(f.get(k, ""))

    area_raw = f.get("建筑面积", "")
    if area_raw:
        m = re.search(r"[\d.]+", area_raw)
        if m and float(m.group()) <= 1_000_000:
            f["建筑面积"] = m.group()
        else:
            f["建筑面积"] = ""

    sp = data.get("start_price")
    rp = data.get("ref_price")
    rpt = data.get("ref_price_type", "")

    if sp:
        f["起拍价"] = _fmt_num(float(sp) / 10000)
    else:
        pi_sp = _get_prop(pi, ["起拍价"])
        f["起拍价"] = pi_sp if pi_sp else ""

    if rp:
        f["参考价"] = _fmt_num(float(rp) / 10000)
    else:
        pi_rp = _get_prop(pi, ["评估价", "处置参考价", "标的评估价"])
        f["参考价"] = pi_rp if pi_rp else ""

    f["参考价类型"] = rpt if rpt else ""

    st = data.get("start_time")
    if hasattr(st, "strftime"):
        f["开拍时间"] = st.strftime("%Y-%m-%d %H:%M")
    elif st:
        f["开拍时间"] = str(st)[:16]
    else:
        f["开拍时间"] = ""

    sp_f = float(sp) if sp else 0.0
    rp_f = float(rp) if rp else 0.0
    f["折扣率"] = _fmt_num(sp_f / rp_f * 10, 1) if rp_f > 0 else ""

    area_m = 0.0
    area_str = f.get("建筑面积", "")
    if area_str:
        am = re.search(r"[\d.]+", area_str)
        if am:
            area_m = float(am.group())
    f["单价"] = _fmt_num(sp_f / area_m / 10000) if area_m > 0 and sp_f > 0 else ""
    if f.get("单价"):
        try:
            if float(f["单价"]) < 0.005:
                f["单价"] = ""
        except ValueError:
            f["单价"] = ""
    f["省额"] = _fmt_num((rp_f - sp_f) / 10000) if rp_f > 0 and sp_f > 0 else ""

    def _dist_m(s) -> float | None:
        m = re.match(r"([\d.]+)\s*(m|km)?", str(s))
        if not m:
            return None
        v = float(m.group(1))
        return v * 1000 if m.group(2) == "km" else v

    def _min_dist(items) -> str:
        best: float | None = None
        for it in items:
            if not isinstance(it, dict) or not it.get("distance"):
                continue
            d = _dist_m(it["distance"])
            if d is None:
                continue
            if best is None or d < best:
                best = d
        if best is None:
            return ""
        return str(int(best)) if best == int(best) else f"{best:g}"

    def _poi_items(cat_data) -> list:
        if isinstance(cat_data, list):
            return cat_data
        if isinstance(cat_data, dict):
            out: list = []
            for v in cat_data.values():
                if isinstance(v, list):
                    out.extend(v)
            return out
        return []

    def _prefer_subcat(cat_data, prefer: list[str]) -> str:
        if isinstance(cat_data, dict):
            for sub in prefer:
                sub_items = cat_data.get(sub)
                if isinstance(sub_items, list) and sub_items:
                    d = _min_dist(sub_items)
                    if d:
                        return d
        return _min_dist(_poi_items(cat_data))

    poi: dict = data.get("poi", {}) or {}
    trans = poi.get("transportation") or {}
    f["最近地铁距离"] = _min_dist(trans.get("地铁", [])) if isinstance(trans, dict) else ""
    f["最近学校距离"] = _prefer_subcat(poi.get("education"), ["小学", "中学"])
    f["最近商场距离"] = _prefer_subcat(poi.get("shopping"), ["购物中心"])
    f["最近医院距离"] = _prefer_subcat(poi.get("medical"), ["综合医院", "其他医院"])
    f["最近公园距离"] = _min_dist(_poi_items(poi.get("parks")))

    return f


# ─── CSV 话术填充 ───

def _load_csv_templates() -> list[dict]:
    with open(CSV_PATH, encoding="utf-8-sig") as fp:
        return list(csv.DictReader(fp))


def _relax_fill(text: str, fields: dict[str, str]) -> str:
    """宽松填充: 含未填占位符的整段(按标点切段)整段丢弃, 其余段落保留并填充。"""
    segs = re.split(r"(?<=[，。；！？、])", text)
    kept: list[str] = []
    for seg in segs:
        names = re.findall(r"\{(\w+)\}", seg)
        if not names:
            kept.append(seg)
        elif all(fields.get(n) for n in names):
            kept.append(seg)
    return "".join(kept).format(**fields)


def _no_discount(cand: str) -> bool:
    """起拍=评估价(无折扣)时, 「10折/立省≤0」句式无意义 → 该候选行跳过。"""
    if re.search(r"10\.?0*折", cand):
        return True
    m = re.search(r"立省(-?[\d.]+)万", cand)
    return bool(m and float(m.group(1)) <= 0)


_POI_FIELDS = ("最近地铁距离", "最近学校距离", "最近商场距离", "最近医院距离", "最近公园距离")

# 「步行范围」宣称覆盖的类别(实测配套行)与阈值: 全部存在且 ≤ 该米数才放行
_WALKING_RANGE_M = 1200.0
_WALKING_CATEGORIES = ("最近地铁距离", "最近学校距离", "最近医院距离", "最近公园距离")


def _walking_ok(fields: dict) -> bool:
    """断言「步行范围」所宣称类别的距离全部存在且 ≤ 阈值(否则宣称虚假)。"""
    for k in _WALKING_CATEGORIES:
        v = fields.get(k)
        if not v:
            return False
        try:
            if float(v) > _WALKING_RANGE_M:
                return False
        except ValueError:
            return False
    return True


def _row_allowed(row: dict, source: str, fields: dict) -> bool:
    """行级准入(备注为声明式条件, 规则判定):
    - 含「仅 ali」: 要求 source=ali 且至少一项 POI 距离非空;
    - 含「步行范围」: 要求地铁/学校/医院/公园距离全部存在且 ≤ 阈值(防止"有 POI≠步行范围")。
    """
    note = (row.get("备注") or "").strip()
    if "仅 ali" in note:
        if source != "ali":
            return False
        if not any(fields.get(k) for k in _POI_FIELDS):
            return False
    if "步行范围" in note:
        if not _walking_ok(fields):
            return False
    return True


def _angle_pool(angle_rows: dict, fields: dict, angle: str, source: str = "") -> tuple[list, list, list]:
    """收集某角度的候选行: (全填行, 宽松行, 固定行), 元素为 (文案, 行元数据)。"""
    full: list[tuple[str, dict]] = []
    relax: list[tuple[str, dict]] = []
    fixed: list[tuple[str, dict]] = []
    for row in angle_rows.get(angle, []):
        if not _row_allowed(row, source, fields):
            continue
        text = row["话术模板"]
        allow_relax = (row.get("宽松填充") or "是") != "否"
        names = re.findall(r"\{(\w+)\}", text)
        if not names:
            fixed.append((text, row))
            continue
        ok = [n for n in names if fields.get(n)]
        if len(ok) == len(names):
            cand = _clean_text(text.format(**fields))
            if cand and not _no_discount(cand):
                full.append((cand, row))
        elif allow_relax and len(ok) * 2 >= len(names):
            cand = _clean_text(_relax_fill(text, fields))
            if cand and not _no_discount(cand):
                relax.append((cand, row))
    return full, relax, fixed


def fill_templates(fields: dict[str, str], seed: str = "", source: str = "") -> dict[str, str]:
    """填充 CSV 模板, 返回 {角度: 已填文案}(全填 → 宽松 → 固定, item_id 种子随机)。"""
    filled, _ = fill_templates_meta(fields, seed=seed, source=source)
    return filled


def fill_templates_meta(fields: dict[str, str], seed: str = "",
                        source: str = "") -> tuple[dict[str, str], dict[str, dict]]:
    """同 fill_templates, 另返回每角度选中行的元数据 {角度: {子主题, 备注}}。"""
    templates = _load_csv_templates()
    angle_rows: dict[str, list[dict]] = {}
    for t in templates:
        angle_rows.setdefault(t["角度"], []).append(t)

    rnd = random.Random(seed)
    result: dict[str, str] = {}
    meta: dict[str, dict] = {}
    for angle in ANGLE_ORDER:
        full, relax, fixed = _angle_pool(angle_rows, fields, angle, source)
        pool = full or relax or fixed
        if pool:
            text, row = rnd.choice(pool)
            result[angle] = text
            meta[angle] = {"子主题": row.get("子主题", ""), "备注": row.get("备注", "")}
    return {a: t for a, t in result.items() if t.strip()}, meta


def build_full_script(filled: dict[str, str]) -> str:
    """按角度顺序拼接完整口播稿文本。"""
    return "\n".join(f"【{a}】{filled[a]}" for a in ANGLE_ORDER if a in filled)


# ─── DB ───

def _get_listing(source: str, item_id: str) -> Optional[dict]:
    from db import session_scope
    from db.listing import Listing
    with session_scope() as s:
        row = s.query(Listing).filter_by(source=source, item_id=item_id).first()
        if not row:
            return None
        data = dict(row.data) if row.data else {}
        if row.start_price:
            data.setdefault("start_price", float(row.start_price))
        if row.ref_price:
            data.setdefault("ref_price", float(row.ref_price))
        if row.ref_price_type:
            data.setdefault("ref_price_type", row.ref_price_type)
        return {"source": source, "item_id": item_id, "title": row.title or "", "data": data}


def _write_script(source: str, item_id: str, full_script: str):
    from db import get_source_data, upsert_listing
    entry = get_source_data(source).get(item_id, {})
    new_data = dict(entry.get("data", {}))
    new_data["script"] = full_script
    ok = upsert_listing({
        "source": source,
        "item_id": item_id,
        "title": entry.get("title", ""),
        "data": new_data,
    })
    tag = "OK" if ok else "FAIL"
    print(f"[DB {tag}] script → {source}/{item_id}")


# ─── 主流程 ───

def generate(source: str, item_id: str, *, llm: bool = False,
             dry_run: bool = False) -> dict:
    """为单套生成话术, 写回 DB data.script。返回 {角度: 文案}。

    默认纯规则(素材库随机+清洗+校验), --llm 为显式选择的 LLM 润色增强。
    """
    listing = _get_listing(source, item_id)
    if not listing:
        print(f"[SKIP] {source}/{item_id}: not in DB")
        return {}

    data = listing["data"]
    title = listing["title"] or ""
    fields = extract_fields(data, title)
    rule = fill_templates(fields, seed=item_id, source=source)
    if not rule:
        print(f"[SKIP] {item_id}: no fillable templates")
        return {}

    used_llm = False
    if llm:
        _scripts_dir = str(Path(__file__).resolve().parent)
        if _scripts_dir not in sys.path:
            sys.path.insert(0, _scripts_dir)
        from llm_enhance import enhance
        polished = enhance(rule, fields, source=source)
        if polished:
            rule = polished
            used_llm = True

    full_script = build_full_script(rule)
    if dry_run:
        print(full_script)
        print(f"[DRY-RUN] {source}/{item_id} llm={'on' if used_llm else 'off'}")
    else:
        _write_script(source, item_id, full_script)
    return rule


def run_all(source: str = "gpai", limit: int = 5, force: bool = False,
            llm: bool = False, workers: int = 4, dry_run: bool = False):
    """批量生成话术(幂等: 已有 data.script 默认跳过, --force 强制; --llm 走 LLM 增强)。"""
    from db import get_source_data
    data_map = get_source_data(source)
    items = [it for it, e in data_map.items()
             if not (not force and (e.get("data") or {}).get("script"))]
    items = items[:limit] if limit and limit > 0 else items

    done = skipped = 0
    if llm and workers > 1 and len(items) > 1:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(generate, source, it, llm=True, dry_run=dry_run): it
                       for it in items}
            for fut in futures:
                if fut.result():
                    done += 1
                else:
                    skipped += 1
    else:
        for it in items:
            print(f"\n=== {source}/{it} ===")
            if generate(source, it, llm=llm, dry_run=dry_run):
                done += 1
            else:
                skipped += 1
    print(f"\n[DONE] generated={done} skipped(already done)={skipped}")


# ─── CLI ───

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="法拍房话术(口播稿)生成")
    ap.add_argument("--source", default="gpai")
    ap.add_argument("--item-id", help="单套房源 ID")
    ap.add_argument("--all", action="store_true", help="批量模式(已有话术则跳过)")
    ap.add_argument("--force", action="store_true", help="批量模式下强制重生成")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--llm", action="store_true", help="用 LLM 润色增强(默认纯规则; 显式选择才开启)")
    ap.add_argument("--workers", type=int, default=4, help="LLM 批量并发数")
    ap.add_argument("--dry-run", action="store_true", help="只打印不写库")
    args = ap.parse_args()

    if args.item_id:
        generate(args.source, args.item_id, llm=args.llm, dry_run=args.dry_run)
    elif args.all:
        run_all(args.source, args.limit, force=args.force, llm=args.llm,
                workers=args.workers, dry_run=args.dry_run)
    else:
        ap.print_help()
