"""探针: 打开 desc+prop 均空(_empty标记)的记录,实测页面是否真无公告/属性。"""
from __future__ import annotations

import asyncio
import importlib.util
import random
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

from db import session_scope  # noqa: E402
from sqlalchemy import text  # noqa: E402


async def _run(limit: int = 5) -> int:
    from playwright.async_api import async_playwright
    from utils.browser import get_profile

    with session_scope() as s:
        rows = s.execute(text(
            "SELECT item_id, url FROM listings WHERE source='ali' "
            "AND (data->>'description' IS NULL OR data->>'description' = '') "
            "AND (data->>'property_info' IS NULL OR data->>'property_info' = '' "
            "OR data->>'property_info' = '{}') AND data->>'_empty' = 'true' "
            "ORDER BY start_time DESC LIMIT :lim"), {"lim": limit}).fetchall()
    targets = [(r.item_id, r.url) for r in rows]
    print(f"抽查 {len(targets)} 条 _empty(desc+prop均空)", flush=True)

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
            for item_id, url in targets:
                await page.wait_for_timeout(int(random.uniform(2500, 4500)))
                rpage = await ALI._open_detail_page(url, browser, page=page)
                # 实测公告
                desc = await ALI._fetch_description(rpage)
                # 实测属性
                prop = await ALI._fetch_property_info(rpage)
                if not prop:
                    prop = await ALI._fetch_property_info_from_intro(rpage)
                print(f"{item_id} | 实测 desc={len(desc)}字 prop={len(prop)}项  -> "
                      f"{'确实都空' if not desc and not prop else '其实可抓到!'}"
                      f" | url={rpage.url[:70]}", flush=True)
        finally:
            await browser.close()
    return 0


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    asyncio.run(_run(lim))