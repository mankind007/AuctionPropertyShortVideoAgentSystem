"""一次性补属性: 对指定 item_ids 的阿里记录补 property_info(仅当缺失时)。"""
from __future__ import annotations

import asyncio
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

from db import session_scope, upsert_listing  # noqa: E402
from sqlalchemy import text  # noqa: E402

ITEMS = ["1074103694214", "1074102830637", "1073050233742", "1072197643021",
         "1071316609892", "1071181323991", "1071058461504", "1071044985602",
         "1070998906599", "1070005550884", "1068970663700", "1068961443122",
         "1068675219484"]


async def _run() -> int:
    from playwright.async_api import async_playwright
    from utils.browser import get_profile

    with session_scope() as s:
        rows = s.execute(text(
            "SELECT item_id, url, data FROM listings WHERE source='ali' AND item_id = ANY(:items)"),
            {"items": ITEMS}).fetchall()
    targets = [(r.item_id, r.url, (r.data or {})) for r in rows]
    print(f"目标 {len(targets)} 条", flush=True)

    profile = get_profile()
    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            str(ALI.PROFILE_DIR), headless=False, user_agent=profile["ua"],
            viewport={"width": 1366, "height": 900}, locale="zh-CN",
            timezone_id="Asia/Shanghai", args=ALI.LAUNCH_ARGS,
            ignore_default_args=["--enable-automation"],
        )
        page = browser.pages[0] if browser.pages else await browser.new_page()
        try:
            for item_id, url, data in targets:
                await page.wait_for_timeout(int(__import__("random").uniform(1500, 3500)))
                rpage = await ALI._open_detail_page(url, browser, page=page)
                prop = await ALI._fetch_property_info(rpage)
                if not prop:
                    prop = await ALI._fetch_property_info_from_intro(rpage)
                print(f"{item_id} prop={len(prop)} 项", flush=True)
                if prop:
                    data2 = dict(data)
                    data2["property_info"] = prop
                    data2.pop("_empty", None)
                    upsert_listing({"source": "ali", "item_id": item_id, "data": data2})
                    print(f"  upserted {item_id}", flush=True)
                await rpage.wait_for_timeout(1000)
        finally:
            await browser.close()
    return 0


if __name__ == "__main__":
    asyncio.run(_run())