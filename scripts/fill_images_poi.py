"""脚本: 为 DB 中标缺图片(images)或周围情况(poi,阿里)的房源单独补抓。

与 fill_description_location.py 分工: 那个补 描述/位置/标的物属性(纯文本);
本脚本只补 图片 与 poi —— 这两个抓取耗时(轮播下载 + 高德 iframe 标签切换),单独跑互不影响。

原理: 巡检 DB 中 ali 房源缺 images(空或本地文件缺失)或缺 poi 的记录,逐个打开详情页
抓取后合并回 data 并 upsert;不触碰已存在的 description/location/property_info 等字段。
断点续传以 DB + 本地文件为准:
  - poi: data 已存在 `poi` 键(即使各项为空)视为已采,不重复刷新
  - 图片: DB 无图(空/[])→ 开页抓 URL 并下载;DB 有 url 但本地缺 → 离线补下(不开页)

用法:
    python scripts/fill_images_poi.py [--source ali] [--limit 100] [--workers 3]
    python scripts/fill_images_poi.py --only poi          # 只补周围情况,跳过图片
    python scripts/fill_images_poi.py --only images       # 只补图片
说明: 图片下载到 assets/ali/{item_id}/imgs/;poi 存 data.poi(JSONB)。
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

_ALI = PROJECT_ROOT / "skills" / "ali-assets-crawler" / "scripts" / "crawler.py"
ALI_ROOT = PROJECT_ROOT / "assets" / "ali"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ALI = _load(_ALI, "ali_crawler")

from db import session_scope, upsert_listing  # noqa: E402


def _images_file_ok(item_id: str, imgs: list) -> bool:
    """DB 图片清单是否本地文件齐全(断点续传判断)。"""
    if not imgs:
        return False
    return all(
        x.get("file") and (ALI_ROOT / item_id / "imgs" / x["file"]).exists()
        for x in imgs
    )


def _missing(only: str, limit: int) -> list:
    """返回待补抓 [(item_id, url, data)]。

    images 缺: data->>'images' 为空 / 非数组 / 空数组;
    poi 缺:   data->'poi' IS NULL(与 get_source_poi 语义一致)。
    only: images / poi / both(任一缺)。
    注意: data 为 PostgreSQL `json` 列,判断空一律用 `->>` 文本比较。
    """
    from sqlalchemy import text

    images_needed = ("(data->>'images' IS NULL OR data->>'images' = '' "
                     "OR data->>'images' = '[]')")
    poi_needed = "(data->'poi' IS NULL)"
    if only == "images":
        cond = images_needed
    elif only == "poi":
        cond = poi_needed
    else:
        cond = f"({images_needed}) OR ({poi_needed})"
    sql = ("SELECT item_id, url, data FROM listings "
           f"WHERE source='ali' AND ({cond}) ORDER BY item_id DESC")
    if limit > 0:
        sql += f" LIMIT {limit}"
    out = []
    try:
        with session_scope() as s:
            for item_id, url, data in s.execute(text(sql)):
                out.append((item_id, url, (data or {})))
    except Exception as e:  # noqa: BLE001
        print(f"  ! 查询 DB 失败: {e}", flush=True)
    return out


async def _run_source(only: str, limit: int, headless: bool, workers: int) -> int:
    rows = _missing(only, limit)
    print(f"[ali] 待补抓 {len(rows)} 条(only={only}),并行标签页 {workers} 个", flush=True)
    if not rows:
        return 0
    from playwright.async_api import async_playwright
    from utils.browser import STEALTH_SCRIPT

    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            str(ALI.PROFILE_DIR), headless=headless, user_agent=ALI.UA,
            viewport={"width": 1366, "height": 900}, locale="zh-CN",
            timezone_id="Asia/Shanghai", args=ALI.LAUNCH_ARGS,
            ignore_default_args=["--enable-automation"],
        )
        pages = [await browser.new_page() for _ in range(workers)]

        items_q = asyncio.Queue()
        for r in rows:
            await items_q.put(r)

        async def worker(page) -> int:
            n_ok = 0
            opened = 0
            while True:
                try:
                    item = items_q.get_nowait()
                except asyncio.QueueEmpty:
                    return n_ok
                opened += 1
                if opened % 5 == 0:
                    await page.wait_for_timeout(int(random.uniform(2000, 3500)))
                else:
                    await page.wait_for_timeout(int(random.uniform(800, 2000)))
                item_id, url, data = item
                try:
                    need_images = only in ("images", "both") and not data.get("images")
                    need_poi = only in ("poi", "both") and data.get("poi") is None
                    need_open = need_images or need_poi
                    if not need_open:
                        # 图片缺但 DB 有 url → 离线补下,不开页
                        if only == "images" and data.get("images") and not _images_file_ok(item_id, data["images"]):
                            from app.schemas.listing import AuctionDetail

                            detail = AuctionDetail(
                                source="ali", item_id=item_id,
                                images=[x["url"] for x in data["images"]],
                            )
                            structured = ALI.download_images(detail, item_id, ALI_ROOT)
                            data2 = dict(data)
                            data2["images"] = structured
                            upsert_listing({"source": "ali", "item_id": item_id, "data": data2})
                            n_ok += 1
                            print(f"  [ali] {item_id} 离线补图 {len([f for f in structured if f.get('file')])} 张", flush=True)
                        else:
                            print(f"  [ali] {item_id} 已齐,跳过", flush=True)
                        continue

                    # 复用本标签页打开详情,避免逐条开新页
                    rpage = await ALI._open_detail_page(url, browser, page=page)
                    data = dict(data)
                    if need_images:
                        imgs = await ALI._fetch_images(rpage)
                        detail = ALI.AuctionDetail(source="ali", item_id=item_id, images=imgs)
                        structured = ALI.download_images(detail, item_id, ALI_ROOT)
                        data["images"] = structured
                    if need_poi:
                        poi = await ALI._fetch_surrounding_info(rpage, browser)
                        data["poi"] = {
                            "transportation": poi.get("transportation", {}),
                            "education": poi.get("education", {}),
                            "shopping": poi.get("shopping", {}),
                            "medical": poi.get("medical", {}),
                            "parks": poi.get("parks", []),
                        }
                    data.pop("_empty", None)
                    upsert_listing({"source": "ali", "item_id": item_id, "data": data})
                    n_ok += 1
                    print(f"  [ali] {item_id} 图 {len(data.get('images') or [])} 张 / poi {len(data.get('poi') or {})}", flush=True)
                except Exception as e:  # noqa: BLE001
                    print(f"  [ali] {item_id} 抓取失败: {e} | {url}", flush=True)
            return n_ok

        results = await asyncio.gather(*(worker(pg) for pg in pages))
        await browser.close()
    return sum(results)


def main() -> int:
    parser = argparse.ArgumentParser(description="为 DB 中标缺图片/周围情况(poi)的记录单独补抓")
    parser.add_argument("--only", default="both", choices=["images", "poi", "both"],
                        help="补什么: images 只补图 / poi 只补周围 / both(默认)两者都补")
    parser.add_argument("--limit", type=int, default=0, help="最多补几条(0=全部)")
    parser.add_argument("--headless", action="store_true", default=False,
                        help="无头模式(需已登录 profile)")
    parser.add_argument("--workers", type=int, default=3,
                        help="并行标签页数(固定数量复用,默认 3)")
    args = parser.parse_args()
    total = asyncio.run(_run_source(args.only, args.limit, args.headless, args.workers))
    print(f"完成,共补抓 {total} 条", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())