"""promo-image: 法拍房宣传海报合成。

读 DB + CSV → 填充话术占位符 → 逐张房源图合成「标题+图+话术」海报 → 写回 DB。
每套房源的所有海报尺寸统一(canvas 由该套图片和字体度量推导,不硬编码)。
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

# ─── 路径 ───
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
FONTS_DIR = PROJECT_ROOT / "assets" / "fonts"
CSV_PATH = PROJECT_ROOT / "assets" / "短视频宣传话术.csv"

# ─── 字体 ───
TITLE_FONT_CANDIDATES = ["江城律动圆.ttf"]
BODY_FONT_CANDIDATES = ["极影毁片圆.ttf", "SGH-Medium.ttf", "SGH-Light.ttf"]

# ─── 角度逻辑顺序(决定海报编号与内容推进) ───
# 开场钩子(吸睛)→ 硬指标 → 价格 → 地段 → 常见误区 → 风险 → 紧迫感 → 行动号召(收尾)
ANGLE_ORDER = [
    "开场钩子", "房源硬指标", "价格解析", "地段与配套",
    "常见误区", "风险提示", "紧迫感", "行动号召",
]

# 首尾固定角度(首图吸睛, 末图收尾)
_FIRST_ANGLE = "开场钩子"
_LAST_ANGLE = "行动号召"


def _assign_angles(n_images: int, filled: dict[str, str]) -> list[str]:
    """为 N 张图分配角度: 首图=开场钩子, 末图=行动号召, 中间按逻辑序循环。

    保证开场在最前、号召在最后, 中间不重复堆积同一角度(除非图多于可用角度)。
    """
    avail = [a for a in ANGLE_ORDER if a in filled]
    if not avail:
        return []
    middle = [a for a in avail if a not in (_FIRST_ANGLE, _LAST_ANGLE)]

    result: list[str] = []
    for i in range(n_images):
        if i == 0 and _FIRST_ANGLE in filled:
            result.append(_FIRST_ANGLE)
        elif i == n_images - 1 and _LAST_ANGLE in filled:
            result.append(_LAST_ANGLE)
        elif middle:
            # 中间按逻辑序从首项开始填充, 不跳号
            result.append(middle[(i - 1) % len(middle)])
        else:
            # 仅有首/尾角度时, 中间循环可用角度(不含首尾避免连续重复)
            loop = [a for a in avail if a not in (_FIRST_ANGLE, _LAST_ANGLE)] or avail
            result.append(loop[(i - 1) % len(loop)])
    return result

# ─── property_info 候选键 ───
FIELD_KEYS: Dict[str, List[str]] = {
    "小区名称": ["小区名称", "标的物名称", "拍品名称", "项目名称", "标的名称"],
    "坐落": ["坐落"],
    "建筑面积": ["建筑面积", "建筑总面积", "房屋建筑面积", "套内面积", "总面积"],
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

def _find_font(candidates: list[str]) -> Path:
    """在 assets/fonts/ 下按候选名找字体, 找不到则取首个 .ttf。"""
    for name in candidates:
        p = FONTS_DIR / name
        if p.exists():
            return p
    for p in FONTS_DIR.rglob("*.ttf"):
        return p
    raise FileNotFoundError(f"No font found, tried: {candidates}")


def _get_prop(info: dict, keys: list[str], default: str = "") -> str:
    """从 property_info 按候选键取第一个非空值。"""
    for k in keys:
        v = info.get(k)
        if v is not None and str(v).strip():
            return str(v).strip()
    return default


def _wrap_chinese(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """中文逐字符换行(按像素宽度), 不依赖空格分词。"""
    lines: list[str] = []
    current = ""
    for char in text:
        test = current + char
        bbox = font.getbbox(test)
        if bbox[2] - bbox[0] > max_width and current:
            lines.append(current)
            current = char
        else:
            current = test
    if current:
        lines.append(current)
    return lines if lines else [""]


# 中文标点集合(用于清理连续标点)
_PUNCT = "，。、；：！？…—·"


def _clean_text(s: str) -> str:
    """清理填充后文本: 合并连续标点(占位符缺失导致的'，，'/'：；'等), 并去除行首因空占位符产生的标点。

    仅处理「连续标点」与「行首标点」, 保留句末正常的！？。等(避免误删正常结尾)。
    """
    out: list[str] = []
    for ch in s:
        if ch in _PUNCT and out and out[-1] in _PUNCT:
            continue
        out.append(ch)
    s = "".join(out).strip()
    # 仅去除行首标点(空占位符导致的 ',采光' → '采光')
    while s and s[0] in _PUNCT:
        s = s[1:].strip()
    return s


# ─── 字段提取 ───

def extract_fields(data: dict, title: str) -> dict[str, str]:
    """从房源 data + title 提取所有模板填充字段(含派生)。"""
    pi: dict = data.get("property_info", {}) or {}
    f: dict[str, str] = {}

    f["标题"] = title or ""
    f["小区名称"] = _get_prop(pi, FIELD_KEYS["小区名称"], default=title)

    # 区域: 从 title / 坐落提取首个「XX区/县/市」
    f["区域"] = ""
    for src in [title, _get_prop(pi, FIELD_KEYS["坐落"])]:
        if src:
            m = re.search(r"([\u4e00-\u9fff]{2,3}?)(区|县|市)", src)
            if m:
                f["区域"] = m.group(1) + m.group(2)
                break

    # property_info 字段
    for field, keys in FIELD_KEYS.items():
        if field not in f:
            f[field] = _get_prop(pi, keys)

    # 保证金/增价幅度: 去掉"万元"等单位,保留数字
    for k in ["保证金", "增价幅度"]:
        v = f.get(k, "")
        if v:
            m = re.search(r"[\d.]+", v)
            f[k] = m.group() if m else ""

    # 建筑面积: 去掉"平方米/㎡/m²"等单位,保留数字(模板会加㎡)
    area_raw = f.get("建筑面积", "")
    if area_raw:
        m = re.search(r"[\d.]+", area_raw)
        f["建筑面积"] = m.group() if m else ""

    # 价格 → 万元(优先用顶层列,元→万; 若无则用 property_info 已是万元的值)
    sp = data.get("start_price")
    rp = data.get("ref_price")
    rpt = data.get("ref_price_type", "")

    if sp:
        f["起拍价"] = f"{float(sp) / 10000:.2f}"
    else:
        pi_sp = _get_prop(pi, ["起拍价"])
        f["起拍价"] = pi_sp if pi_sp else ""

    if rp:
        f["参考价"] = f"{float(rp) / 10000:.2f}"
    else:
        pi_rp = _get_prop(pi, ["评估价", "处置参考价", "标的评估价"])
        f["参考价"] = pi_rp if pi_rp else ""

    f["参考价类型"] = rpt if rpt else ""

    # 开拍时间
    st = data.get("start_time")
    if hasattr(st, "strftime"):
        f["开拍时间"] = st.strftime("%Y-%m-%d %H:%M")
    elif st:
        f["开拍时间"] = str(st)[:16]
    else:
        f["开拍时间"] = ""

    # 派生
    sp_f = float(sp) if sp else 0.0
    rp_f = float(rp) if rp else 0.0
    f["折扣率"] = f"{sp_f / rp_f * 10:.1f}" if rp_f > 0 else ""

    area_m = 0.0
    area_str = f.get("建筑面积", "")
    if area_str:
        am = re.search(r"[\d.]+", area_str)
        if am:
            area_m = float(am.group())
    f["单价"] = f"{sp_f / area_m / 10000:.2f}" if area_m > 0 and sp_f > 0 else ""
    f["省额"] = f"{(rp_f - sp_f) / 10000:.2f}" if rp_f > 0 and sp_f > 0 else ""

    # POI 距离(ali only)
    poi: dict = data.get("poi", {}) or {}
    for cat, key in [
        ("transportation", "最近地铁距离"), ("education", "最近学校距离"),
        ("shopping", "最近商场距离"), ("medical", "最近医院距离"),
        ("parks", "最近公园距离"),
    ]:
        items = poi.get(cat, [])
        if isinstance(items, list) and items:
            dists = [it.get("distance") for it in items if it.get("distance") is not None]
            f[key] = str(min(dists)) if dists else ""
        else:
            f[key] = ""

    return f


# ─── CSV 话术填充 ───

def _load_csv_templates() -> list[dict]:
    with open(CSV_PATH, encoding="utf-8-sig") as fp:
        return list(csv.DictReader(fp))


def fill_templates(fields: dict[str, str]) -> dict[str, str]:
    """填充 CSV 模板, 返回 {角度: 已填文案}。占位符缺失时跳该行。"""
    templates = _load_csv_templates()
    angle_rows: dict[str, list[dict]] = {}
    for t in templates:
        angle_rows.setdefault(t["角度"], []).append(t)

    result: dict[str, str] = {}
    for angle in ANGLE_ORDER:
        for row in angle_rows.get(angle, []):
            text = row["话术模板"]
            try:
                filled = text.format(**fields)
                if "{" not in filled:
                    result[angle] = _clean_text(filled)
                    break
            except (KeyError, ValueError):
                continue
    # 过滤掉清理后变空的文案(整行仅标点)
    return {a: t for a, t in result.items() if t.strip()}


# ─── 海报合成 ───

def _text_height(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> int:
    """计算换行后文本像素高度。"""
    lines = _wrap_chinese(text, font, max_width)
    return int(len(lines) * font.size * 1.5)


def _compose_poster(
    photo: Image.Image,
    title_lines: list[str],
    copy: str,
    title_font: ImageFont.FreeTypeFont,
    body_font: ImageFont.FreeTypeFont,
    canvas_width: int,
    photo_area_height: int,
    title_height: int,
    copy_height: int,
) -> Image.Image:
    """合成单张海报: 顶部标题(居中,可多行) + 中部原图(contain) + 底部话术(居中)。"""
    canvas_height = title_height + photo_area_height + copy_height
    canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
    draw = ImageDraw.Draw(canvas)
    margin = 20

    # ── 标题带(水平居中, 垂直居中, 支持多行换行) ──
    t_lh = title_font.getbbox("测")[3] - title_font.getbbox("测")[1]
    y = (title_height - t_lh * len(title_lines)) // 2
    for line in title_lines:
        bbox = title_font.getbbox(line)
        tw = bbox[2] - bbox[0]
        draw.text(((canvas_width - tw) // 2, y), line, font=title_font, fill="black")
        y += t_lh

    # ── 图片带(contain, 居中) ──
    ratio = min(canvas_width / photo.width, photo_area_height / photo.height)
    new_w, new_h = int(photo.width * ratio), int(photo.height * ratio)
    resized = photo.resize((new_w, new_h), Image.LANCZOS)
    px = (canvas_width - new_w) // 2
    py = title_height + (photo_area_height - new_h) // 2
    canvas.paste(resized, (px, py))

    # ── 话术带(水平居中, 垂直居中, 自动换行) ──
    copy_lines = _wrap_chinese(copy, body_font, canvas_width - margin * 2)
    c_lh = int(body_font.size * 1.5)
    y = title_height + photo_area_height + (copy_height - c_lh * len(copy_lines)) // 2
    for line in copy_lines:
        bbox = body_font.getbbox(line)
        lw = bbox[2] - bbox[0]
        draw.text(((canvas_width - lw) // 2, y), line, font=body_font, fill="#333333")
        y += c_lh

    return canvas


# ─── DB 读写 ───

def _get_listing(source: str, item_id: str) -> Optional[dict]:
    from db import session_scope
    from db.listing import Listing
    with session_scope() as s:
        row = s.query(Listing).filter_by(source=source, item_id=item_id).first()
        if not row:
            return None
        data = dict(row.data) if row.data else {}
        # 把顶层列合并进 data,供 extract_fields 统一读取
        if row.start_price:
            data.setdefault("start_price", float(row.start_price))
        if row.ref_price:
            data.setdefault("ref_price", float(row.ref_price))
        if row.ref_price_type:
            data.setdefault("ref_price_type", row.ref_price_type)
        return {"source": source, "item_id": item_id, "title": row.title or "", "data": data}


def _get_images(source: str, item_id: str) -> list[Tuple[str, Path]]:
    imgs_dir = PROJECT_ROOT / "assets" / source / item_id / "imgs"
    if not imgs_dir.exists():
        return []
    result = []
    for p in sorted(imgs_dir.iterdir()):
        if p.suffix.lower() in (".png", ".jpg", ".jpeg") and not p.name.startswith("poster_"):
            result.append((p.name, p))
    return result


def _write_db(source: str, item_id: str, full_script: str, script_images: list[dict]):
    from db import get_source_data, upsert_listing
    entry = get_source_data(source).get(item_id, {})
    old_data = entry.get("data", {})
    new_data = dict(old_data)
    new_data["script"] = full_script
    new_data["script_images"] = script_images
    ok = upsert_listing({
        "source": source,
        "item_id": item_id,
        "title": entry.get("title", ""),
        "data": new_data,
    })
    tag = "OK" if ok else "FAIL"
    print(f"[DB {tag}] script_images({len(script_images)}) → {source}/{item_id}")


# ─── 主流程 ───

def run(source: str, item_id: str, output_width: Optional[int] = None) -> dict:
    """为一套房源生成宣传海报, 返回 {poster_count, canvas_size, paths}。"""
    listing = _get_listing(source, item_id)
    if not listing:
        print(f"[SKIP] {source}/{item_id}: not in DB")
        return {}

    data = listing["data"]
    title = listing["title"] or ""

    # 1) 填充话术
    fields = extract_fields(data, title)
    filled = fill_templates(fields)
    if not filled:
        print(f"[SKIP] {item_id}: no fillable templates")
        return {}

    # 2) 取原图
    images_info = _get_images(source, item_id)
    if not images_info:
        print(f"[SKIP] {item_id}: no images in imgs/")
        return {}

    source_images: list[Tuple[str, Image.Image]] = []
    for fname, fpath in images_info:
        try:
            source_images.append((fname, Image.open(fpath).convert("RGB")))
        except Exception as exc:
            print(f"[WARN] open {fpath} failed: {exc}")
    if not source_images:
        return {}

    # 3) 加载字体(正文固定; 标题字号在 _layout_title 内按版式自适应)
    body_font = ImageFont.truetype(str(_find_font(BODY_FONT_CANDIDATES)), size=32)

    # 4) 计算两种版式 canvas 尺寸(严格 9:16 / 16:9, 由图片推导基准宽, 不硬编码像素)
    #    竖版 9:16: 宽=原图最大宽 W, 高=W×16/9
    #    横版 16:9: 高=W, 宽=W×16/9  (与竖版共用同一基准 W)
    ref_w = output_width or max(img.width for _, img in source_images)
    v_width, v_height = ref_w, round(ref_w * 16 / 9)
    h_width, h_height = round(ref_w * 16 / 9), ref_w

    # 话术带高度: 取最长文案所需高度(各版按各自宽度换行)
    v_copy_h = max(_text_height(txt, body_font, v_width - 40) for txt in filled.values()) + 40
    h_copy_h = max(_text_height(txt, body_font, h_width - 40) for txt in filled.values()) + 40

    # 标题排版(各版独立): 过长换行, 若换行后占高过大则缩小字号直到图片区 ≥ 下限
    title_font_path = str(_find_font(TITLE_FONT_CANDIDATES))
    min_photo = 300

    def _layout_title(cw: int, ch: int, copy_h: int):
        size = 48
        while size >= 24:
            f = ImageFont.truetype(title_font_path, size)
            lines = _wrap_chinese(title, f, cw - 40)
            lh = f.getbbox("测")[3] - f.getbbox("测")[1]
            th = lh * len(lines) + 40
            ph = ch - th - copy_h
            if ph >= min_photo:
                return f, lines, th, ph
            size -= 4
        # 兜底: 用最小字号
        f = ImageFont.truetype(title_font_path, 24)
        lines = _wrap_chinese(title, f, cw - 40)
        lh = f.getbbox("测")[3] - f.getbbox("测")[1]
        th = lh * len(lines) + 40
        return f, lines, th, max(ch - th - copy_h, 100)

    v_font, v_title_lines, v_title_h, v_photo_h = _layout_title(v_width, v_height, v_copy_h)
    h_font, h_title_lines, h_title_h, h_photo_h = _layout_title(h_width, h_height, h_copy_h)

    v_canvas = (v_width, v_height)
    h_canvas = (h_width, h_height)
    print(f"[INFO] v_canvas={v_canvas}(9:16), h_canvas={h_canvas}(16:9), "
          f"images={len(source_images)}, angles={len(filled)}, "
          f"v_title_lines={len(v_title_lines)}, h_title_lines={len(h_title_lines)}")

    # 5) 角度分配: 首图=开场钩子, 末图=行动号召, 中间按逻辑序
    angles_assigned = _assign_angles(len(source_images), filled)

    # 6) 生成前清理旧海报
    output_dir = PROJECT_ROOT / "assets" / source / item_id / "imgs"
    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("poster_*.png"):
        old.unlink()

    # 7) 逐图合成(竖版 + 横版, 各一套)
    script_images: list[dict] = []
    for i, (fname, img) in enumerate(source_images):
        angle = angles_assigned[i]

        # 竖版 9:16
        v_poster = _compose_poster(
            img, v_title_lines, filled[angle], v_font, body_font,
            v_width, v_photo_h, v_title_h, v_copy_h,
        )
        v_name = f"poster_{i + 1:02d}_v.png"
        v_poster.save(output_dir / v_name, "PNG")
        script_images.append({
            "file": v_name,
            "copy": filled[angle],
            "angle": angle,
            "source_img": fname,
            "orientation": "vertical",
        })

        # 横版 16:9
        h_poster = _compose_poster(
            img, h_title_lines, filled[angle], h_font, body_font,
            h_width, h_photo_h, h_title_h, h_copy_h,
        )
        h_name = f"poster_{i + 1:02d}_h.png"
        h_poster.save(output_dir / h_name, "PNG")
        script_images.append({
            "file": h_name,
            "copy": filled[angle],
            "angle": angle,
            "source_img": fname,
            "orientation": "horizontal",
        })
        print(f"  → {v_name}/{h_name} angle={angle}")

    # 8) 写库
    angles_seq = [a for a in ANGLE_ORDER if a in filled]
    full_script = "\n".join(f"【{a}】{filled[a]}" for a in angles_seq)
    _write_db(source, item_id, full_script, script_images)

    return {
        "poster_count": len(script_images),
        "canvas_size": {"vertical": v_canvas, "horizontal": h_canvas},
        "paths": [str(output_dir / s["file"]) for s in script_images],
    }


def run_all(source: str = "gpai", limit: int = 5):
    """批量: 遍历有图房源生成海报。"""
    from db import get_source_data
    data_map = get_source_data(source)
    done = 0
    for item_id, entry in data_map.items():
        if done >= limit:
            break
        imgs = (entry.get("data") or {}).get("images", [])
        if not imgs:
            continue
        print(f"\n=== {source}/{item_id} ===")
        r = run(source, item_id)
        if r:
            done += 1
    print(f"\n[DONE] {done} listings processed.")


# ─── CLI ───

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="法拍房宣传海报合成")
    ap.add_argument("--source", default="gpai")
    ap.add_argument("--item-id", help="单套房源 ID")
    ap.add_argument("--all", action="store_true", help="批量模式")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--width", type=int, default=None, help="输出宽度(默认自动)")
    args = ap.parse_args()

    if args.item_id:
        run(args.source, args.item_id, output_width=args.width)
    elif args.all:
        run_all(args.source, args.limit)
    else:
        ap.print_help()
