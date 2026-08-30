"""promo-image: 法拍房宣传海报合成(读稿版)。

话术生成已分离到 skills/script-writer(generate_scripts.py → 写 DB data.script)。
本脚本只负责: 读 DB data.script → 解析 8 角度 → 逐张房源图合成「标题+图+话术」海报 → 写回
data.script_images。海报尺寸由该套图片和字体度量推导,不硬编码。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

# ─── 路径 ───
PROJECT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(PROJECT_ROOT))
FONTS_DIR = PROJECT_ROOT / "assets" / "fonts"

# ─── 字体 ───
TITLE_FONT_CANDIDATES = ["江城律动圆.ttf"]
MAX_CANVAS_W = 1920  # 海报画布宽上限(超大原图会被等比缩小)
BODY_FONT_CANDIDATES = ["极影毁片圆.ttf", "SGH-Medium.ttf", "SGH-Light.ttf"]

# 首尾固定角度(首图吸睛, 末图收尾)
_FIRST_ANGLE = "开场钩子"
_LAST_ANGLE = "行动号召"


def _parse_script(full_script: str) -> dict[str, str]:
    """解析 DB data.script 文本 → {角度: 文案}(保持出现顺序)。"""
    filled: dict[str, str] = {}
    if not full_script:
        return filled
    for m in re.finditer(r"【(.+?)】([^【]*)", full_script):
        angle, text = m.group(1).strip(), m.group(2).strip()
        if angle and text:
            filled[angle] = text
    return filled


def _expand_images(source_images: list) -> list:
    """少图房源保底 4 张海报: 1图→[A,A,A,A]; 2图→[A,A,B,B]; ≥3图原样。"""
    n = len(source_images)
    if n == 1:
        return source_images * 4
    if n == 2:
        return [source_images[0], source_images[0], source_images[1], source_images[1]]
    return source_images


def _assign_angles(n_images: int, filled: dict[str, str]) -> list[str]:
    """为 N 张图分配角度: 首图=开场钩子, 末图=行动号召, 中间按话术出现顺序循环。"""
    avail = [a for a in filled if a]
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
            result.append(middle[(i - 1) % len(middle)])
        else:
            loop = [a for a in avail if a not in (_FIRST_ANGLE, _LAST_ANGLE)] or avail
            result.append(loop[(i - 1) % len(loop)])
    return result


# ─── 联系/法务信息(需求.txt 待解决: 图片下方空间足够时左下角标注) ───
CONTACT_LINES = [
    "投资咨询公司：深圳市特资投资集团公司",
    "投资咨询电话：0755-21677539",
    "法律咨询公司：广东勤润律师事务所",
    "法律咨询邮箱：1379246426@qq.com",
]


# ─── 工具函数 ───

def _clean_title(t: str) -> str:
    """海报标题清洗: 去拍次标签(【一拍】等)与括号注释(【…】[…]〔…〕, 含未闭合截断)。"""
    if not t:
        return ""
    t = re.sub(r"^【(一拍|二拍|三拍|变卖|第一次|第二次)】", "", t.strip())
    t = re.sub(r"[\[【〔][^\]】〕]*[\]】〕]", "", t)
    t = re.sub(r"[\[【〔].*$", "", t)
    t = re.sub(r"^[\]】〕].*$", "", t)
    return t.strip()


def _find_font(candidates: list[str]) -> Path:
    """在 assets/fonts/ 下按候选名找字体, 找不到则取首个 .ttf。"""
    for name in candidates:
        p = FONTS_DIR / name
        if p.exists():
            return p
    for p in FONTS_DIR.rglob("*.ttf"):
        return p
    raise FileNotFoundError(f"No font found, tried: {candidates}")


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
    contact_height: int,
    fullbleed: bool = False,
) -> Image.Image:
    """合成单张海报。

    - fullbleed=False(竖版): 标题带 + 图片带(cover 填满) + 话术带 + 左下联系信息, 白底分层。
    - fullbleed=True(横版): 原图铺满整张画布(cover), 仅顶部标题带 / 底部话术+联系带用半透明白底,
      避免横版 16:9 高度有限导致原图变成细条。
    """
    margin = 20
    canvas_height = title_height + photo_area_height + copy_height + contact_height

    if fullbleed:
        ratio = max(canvas_width / photo.width, canvas_height / photo.height)
        new_w, new_h = int(photo.width * ratio), int(photo.height * ratio)
        resized = photo.resize((new_w, new_h), Image.LANCZOS)
        sx = (new_w - canvas_width) // 2
        sy = (new_h - canvas_height) // 2
        resized = resized.crop((sx, sy, sx + canvas_width, sy + canvas_height))
        canvas = resized.convert("RGB")
        draw = ImageDraw.Draw(canvas)
        _band(draw, 0, 0, canvas_width, title_height, 205)
        _band(draw, 0, canvas_height - copy_height - contact_height,
              canvas_width, canvas_height, 205)
    else:
        canvas = Image.new("RGB", (canvas_width, canvas_height), "white")
        draw = ImageDraw.Draw(canvas)
        ratio = max(canvas_width / photo.width, photo_area_height / photo.height)
        new_w, new_h = int(photo.width * ratio), int(photo.height * ratio)
        resized = photo.resize((new_w, new_h), Image.LANCZOS)
        sx = (new_w - canvas_width) // 2
        sy = (new_h - photo_area_height) // 2
        resized = resized.crop((sx, sy, sx + canvas_width, sy + photo_area_height))
        canvas.paste(resized, (0, title_height))

    t_lh = title_font.getbbox("测")[3] - title_font.getbbox("测")[1]
    y = (title_height - t_lh * len(title_lines)) // 2
    for line in title_lines:
        bbox = title_font.getbbox(line)
        tw = bbox[2] - bbox[0]
        draw.text(((canvas_width - tw) // 2, y), line, font=title_font, fill="black")
        y += t_lh

    copy_lines = _wrap_chinese(copy, body_font, canvas_width - margin * 2)
    c_lh = int(body_font.size * 1.5)
    y = title_height + photo_area_height + (copy_height - c_lh * len(copy_lines)) // 2
    for line in copy_lines:
        bbox = body_font.getbbox(line)
        lw = bbox[2] - bbox[0]
        draw.text(((canvas_width - lw) // 2, y), line, font=body_font, fill="#333333")
        y += c_lh

    contact_font = ImageFont.truetype(str(body_font.path), max(16, int(body_font.size * 0.5)))
    clh = int(contact_font.size * 1.3)
    cy = canvas_height - clh * len(CONTACT_LINES) - 8
    for line in CONTACT_LINES:
        draw.text((margin, cy), line, font=contact_font, fill="#777777")
        cy += clh

    return canvas


def _band(draw: ImageDraw.ImageDraw, x0: int, y0: int, x1: int, y1: int, alpha: int) -> None:
    """在 RGB 画布上画半透明白色带(手动 alpha 混合, 兼容 RGB 画布)。"""
    band = Image.new("RGB", (x1 - x0, y1 - y0), (255, 255, 255))
    base = draw._image.crop((x0, y0, x1, y1))
    blended = Image.blend(base, band, alpha / 255.0)
    draw._image.paste(blended, (x0, y0))


# ─── DB 读写 ───

def _get_listing(source: str, item_id: str) -> Optional[dict]:
    from db import session_scope
    from db.listing import Listing
    with session_scope() as s:
        row = s.query(Listing).filter_by(source=source, item_id=item_id).first()
        if not row:
            return None
        data = dict(row.data) if row.data else {}
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
    new_data = dict(entry.get("data", {}))
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
    title = _clean_title(listing["title"] or "")

    # 1) 话术: 读 DB data.script(由 script-writer 生成), 解析 8 角度
    full_script = data.get("script") or ""
    filled = _parse_script(full_script)
    if not filled:
        print(f"[SKIP] {item_id}: no data.script — 请先运行 "
              f"skills/script-writer/scripts/generate_scripts.py")
        return {}

    # 2) 取原图
    images_info = _get_images(source, item_id)
    if not images_info:
        print(f"[SKIP] {item_id}: no images in imgs/")
        return {}

    source_images: list[Tuple[str, Image.Image]] = []
    for fname, fpath in images_info:
        try:
            # with 确保原图句柄立即释放(convert 后副本自持数据), 避免管线运行期间锁住输入图
            with Image.open(fpath) as im:
                source_images.append((fname, im.convert("RGB")))
        except Exception as exc:
            print(f"[WARN] open {fpath} failed: {exc}")
    if not source_images:
        return {}

    # 2.5) 少图保底: 1图/2图 扩到 4 张(同图不同角度话术), 保证视频时长
    source_images = _expand_images(source_images)

    # 4) 计算两种版式 canvas 尺寸(严格 9:16 / 16:9, 由图片推导基准宽)
    # 画布宽上限 1920: 视频端最终也压到 1920 长边, 更大的画布只拖慢/撑爆 ffmpeg
    raw_w = max(img.width for _, img in source_images)
    ref_w = min(output_width or raw_w, raw_w, MAX_CANVAS_W)
    v_width, v_height = ref_w, round(ref_w * 16 / 9)
    h_width, h_height = round(ref_w * 16 / 9), ref_w

    # 3) 字体(按画布宽自适应放大; 标题字号必须 > 正文字号)
    title_font_path = str(_find_font(TITLE_FONT_CANDIDATES))
    body_font_path = str(_find_font(BODY_FONT_CANDIDATES))
    v_title_size = max(40, round(v_width / 16))
    v_body_size = max(26, round(v_width / 26))
    h_title_size = max(40, round(h_width / 20))
    h_body_size = max(24, round(h_width / 34))
    v_body_font = ImageFont.truetype(body_font_path, v_body_size)
    h_body_font = ImageFont.truetype(body_font_path, h_body_size)

    v_copy_h = max(_text_height(txt, v_body_font, v_width - 40) for txt in filled.values()) + 40
    h_copy_h = max(_text_height(txt, h_body_font, h_width - 40) for txt in filled.values()) + 24

    def _contact_h(body_size: int) -> int:
        cs = max(14, int(body_size * 0.45))
        return int(cs * 1.25) * len(CONTACT_LINES) + 6
    v_contact_h = _contact_h(v_body_size)
    h_contact_h = _contact_h(h_body_size)

    min_photo = 300

    def _layout_title(cw: int, ch: int, copy_h: int, contact_h: int,
                     start_size: int, min_size: int):
        size = start_size
        while size >= min_size:
            f = ImageFont.truetype(title_font_path, size)
            lines = _wrap_chinese(title, f, cw - 40)
            lh = f.getbbox("测")[3] - f.getbbox("测")[1]
            th = lh * len(lines) + 40
            ph = ch - th - copy_h - contact_h
            if ph >= min_photo:
                return f, lines, th, ph
            size -= 4
        f = ImageFont.truetype(title_font_path, min_size)
        lines = _wrap_chinese(title, f, cw - 40)
        lh = f.getbbox("测")[3] - f.getbbox("测")[1]
        th = lh * len(lines) + 40
        return f, lines, th, max(ch - th - copy_h - contact_h, 100)

    v_font, v_title_lines, v_title_h, v_photo_h = _layout_title(
        v_width, v_height, v_copy_h, v_contact_h, v_title_size, v_body_size + 4)
    h_font, h_title_lines, h_title_h, h_photo_h = _layout_title(
        h_width, h_height, h_copy_h, h_contact_h, h_title_size, h_body_size + 4)

    v_canvas = (v_width, v_height)
    h_canvas = (h_width, h_height)
    print(f"[INFO] v_canvas={v_canvas}(9:16), h_canvas={h_canvas}(16:9), "
          f"images={len(source_images)}, angles={len(filled)}, "
          f"v_title_lines={len(v_title_lines)}, h_title_lines={len(h_title_lines)}")

    # 5) 角度分配: 首图=开场钩子, 末图=行动号召, 中间按话术顺序
    angles_assigned = _assign_angles(len(source_images), filled)

    # 6) 生成前清理旧海报(输出到 posters/ 目录, 与原始图 imgs/ 分桶)
    output_dir = PROJECT_ROOT / "assets" / source / item_id / "posters"
    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("poster_*.png"):
        old.unlink()

    # 7) 逐图合成(竖版 + 横版, 各一套)
    script_images: list[dict] = []
    for i, (fname, img) in enumerate(source_images):
        angle = angles_assigned[i]

        v_poster = _compose_poster(
            img, v_title_lines, filled[angle], v_font, v_body_font,
            v_width, v_photo_h, v_title_h, v_copy_h, v_contact_h,
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

        h_poster = _compose_poster(
            img, h_title_lines, filled[angle], h_font, h_body_font,
            h_width, h_photo_h, h_title_h, h_copy_h, h_contact_h,
            fullbleed=True,
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

    # 8) 写库(话术原文不动, 仅补 script_images)
    _write_db(source, item_id, full_script, script_images)

    return {
        "poster_count": len(script_images),
        "canvas_size": {"vertical": v_canvas, "horizontal": h_canvas},
        "paths": [str(output_dir / s["file"]) for s in script_images],
    }


def run_all(source: str = "gpai", limit: int = 5, force: bool = False):
    """批量合成海报(幂等: 已有 script_images 默认跳过, --force 重生成)。无话术的房源跳过(先跑 script-writer)。"""
    from db import get_source_data
    data_map = get_source_data(source)
    done = 0
    skipped = 0
    no_script = 0
    for item_id, entry in data_map.items():
        if done >= limit:
            break
        data = entry.get("data") or {}
        if not data.get("images"):
            continue
        if not data.get("script"):
            no_script += 1
            continue
        if not force and data.get("script_images"):
            skipped += 1
            continue
        print(f"\n=== {source}/{item_id} ===")
        r = run(source, item_id)
        if r:
            done += 1
    print(f"\n[DONE] generated={done} skipped(already done)={skipped} no_script={no_script}")


# ─── CLI ───

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="法拍房宣传海报合成(读 data.script 出海报)")
    ap.add_argument("--source", default="gpai")
    ap.add_argument("--item-id", help="单套房源 ID")
    ap.add_argument("--all", action="store_true", help="批量模式(已生成则跳过, 幂等)")
    ap.add_argument("--force", action="store_true", help="批量模式下强制重生成")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--width", type=int, default=None, help="输出宽度(默认自动)")
    args = ap.parse_args()

    if args.item_id:
        run(args.source, args.item_id, output_width=args.width)
    elif args.all:
        run_all(args.source, args.limit, force=args.force)
    else:
        ap.print_help()
