"""探针脚本: 抓取阿里资产详情,打印将入库的 data 结构(不写数据库)。

用途: 查看抓取流程各字段组装后的真实结构(含标的物属性 property_info、
位置 location、周围情况 poi 等),确认后再入库。默认从 DB 里挑"缺描述"的阿里
记录(即 log.txt 里 `描述 0字` 的那批, 往往带「标的物属性」),也可用 --ids 指定。

用法:
    python scripts/probe_ali_detail.py [--limit 6]
    python scripts/probe_ali_detail.py --ids 1075845060425 1074812989697
    python scripts/probe_ali_detail.py --urls "https://sf-item.taobao.com/sf_item/1075845060425.htm"

说明:
- 不写 DB、不下载图片(images 只给 URL 列表)。
- 复用 assets/ali/chrome_profile 登录态;有头模式,遇滑块请人工拖动。
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

_ALI = PROJECT_ROOT / "skills" / "ali-assets-crawler" / "scripts" / "crawler.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ALI = _load(_ALI, "ali_crawler")

from db import session_scope  # noqa: E402


def _missing_urls(limit: int) -> list:
    """取缺描述的阿里记录 [(item_id, url)];这些大概率带「标的物属性」。
    复用 fill_description_location.py 的判缺逻辑, 不等同于全量巡检。
    """
    from sqlalchemy import text

    desc_needed = ("(data->>'description' IS NULL OR data->>'description' = '' "
                   "OR data->>'description' LIKE '%公告详情%')"
                   " AND (data->>'property_info' IS NULL OR data->>'property_info' = ''"
                   " OR data->>'property_info' = '{}')")
    sql = ("SELECT item_id, url FROM listings "
           f"WHERE source='ali' AND ({desc_needed}) ORDER BY item_id DESC LIMIT {limit}")
    try:
        with session_scope() as s:
            return [(item_id, url) for item_id, url in s.execute(text(sql))]
    except Exception as e:  # noqa: BLE001
        print(f"  ! 查询 DB 失败: {e}(可用 --ids 直接指定)", flush=True)
        return []


async def _probe_one(url: str, item_id: str, browser, page) -> dict:
    """抓单个详情并组装 data 结构(与 crawler.py main() 写库一致,仅去图片下载/DB)。"""
    rpage = await ALI._open_detail_page(url, browser, page=page)
    d = ALI.AuctionDetail(source="ali", item_id=item_id)
    d.images = await ALI._fetch_images(rpage)
    d.property_info = await ALI._fetch_property_info(rpage)
    if not d.property_info:
        d.description = await ALI._fetch_description(rpage)
    poi = await ALI._fetch_surrounding_info(rpage, browser)
    d.transportation = poi.get("transportation", {})
    d.education = poi.get("education", {})
    d.shopping = poi.get("shopping", {})
    d.medical = poi.get("medical", {})
    d.parks = poi.get("parks", [])
    loc = await ALI._fetch_location(rpage)

    data = {
        "images": d.images,
        "raw": {},
        "property_info": d.property_info or None,
        "description": d.description or None,
        "location": loc or None,
        "poi": {
            "transportation": d.transportation,
            "education": d.education,
            "shopping": d.shopping,
            "medical": d.medical,
            "parks": d.parks,
        },
    }
    return data


async def _run(ids: list, urls: list, limit: int) -> int:
    if urls:
        targets = [(ALI._extract_item_id(u), u) for u in urls if u]
    elif ids:
        targets = [(i, f"https://sf-item.taobao.com/sf_item/{i}.htm") for i in ids]
    else:
        targets = _missing_urls(limit)
    print(f"目标 {len(targets)} 条", flush=True)
    if not targets:
        print("没有目标(DB 无缺描述记录,或查询失败);可用 --ids/--urls 手动指定", flush=True)
        return 0

    from playwright.async_api import async_playwright
    from utils.browser import get_profile, render_stealth_script

    async with async_playwright() as p:
        profile = get_profile()
        browser = await p.chromium.launch_persistent_context(
            str(ALI.PROFILE_DIR), headless=False, user_agent=profile["ua"],
            viewport={"width": 1366, "height": 900}, locale="zh-CN",
            timezone_id="Asia/Shanghai", args=ALI.LAUNCH_ARGS,
            ignore_default_args=["--enable-automation"],
        )
        page = await browser.new_page()
        await page.set_extra_http_headers({"Accept-Language": "zh-CN,zh;q=0.9"})
        await page.add_init_script(render_stealth_script(profile))
        page.set_default_timeout(30000)

        for i, (item_id, url) in enumerate(targets, start=1):
            try:
                print(f"\n===== [{i}/{len(targets)}] {item_id} =====", flush=True)
                data = await _probe_one(url, item_id, browser, page)
                print(json.dumps(data, ensure_ascii=False, indent=2), flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"  ! {item_id} 抓取失败: {e}", flush=True)
        await browser.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="阿里详情探针: 打印将入库的 data 结构,不写 DB")
    parser.add_argument("--ids", type=str, nargs="+", default=[],
                        help="item_id 列表(自动拼详情 URL)")
    parser.add_argument("--urls", type=str, nargs="+", default=[],
                        help="完整详情 URL 列表")
    parser.add_argument("--limit", type=int, default=6,
                        help="从 DB 缺描述记录中抓取条数(默认 6,0=全部)")
    args = parser.parse_args()
    return asyncio.run(_run(args.ids, args.urls, args.limit))


if __name__ == "__main__":
    sys.exit(main())