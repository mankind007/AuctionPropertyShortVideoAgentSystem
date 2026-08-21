"""探针: 打开阿里详情页,检查页面是否真的有 描述/标的物属性/标的物介绍。

不依赖 _fetch_description 的解析逻辑,直接 dump 原始 DOM 选择器:
- #J_NoticeDetail 是否存在及文本长度/前 80 字
- 标题为「标的物属性」的 div 是否存在
- div.addition-desc.J_Content / #J_ItemDetailContent 是否存在,内含 table 行数
"""
from __future__ import annotations

import argparse
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

SAMPLE_ITEMS = [
    "1074103694214", "1068961443122", "1068970663700", "1071044985602",
    "1068675219484", "1074102830637", "1072197643021", "1071181323991",
    "1073050233742", "1071316609892", "1071058461504", "1070998906599",
    "1070005550884", "1068430672575", "1065682362682",
]


async def _inspect(page, item_id: str) -> dict:
    out = {"item": item_id, "url": page.url[:90]}

    # 1) 公告描述区
    nd = page.locator("xpath=//div[@id='J_NoticeDetail']")
    if await nd.count():
        txt = (await nd.first.inner_text()).strip()
        out["notice"] = f"exists len={len(txt)} head={txt[:80]!r}"
    else:
        out["notice"] = "MISSING"

    # 2) 标的物属性
    lb = page.locator("xpath=//div[normalize-space()='标的物属性']")
    out["prop_label"] = f"exists={await lb.count() > 0}"

    # 3) 标的物介绍 tab 内容表
    intro = page.locator(
        "xpath=//div[contains(@class,'addition-desc') and contains(@class,'J_Content')]"
    )
    out["intro"] = f"exists={await intro.count() > 0}"
    if await intro.count():
        n_tables = await intro.locator("xpath=.//table").count()
        n_tr = await intro.locator("xpath=.//tr").count()
        out["intro"] += f" tables={n_tables} tr={n_tr}"

    # 4) 完整页面文本里是否有「标的物介绍」/「拍卖公告」标题
    body = await page.locator("xpath=//body").inner_text()
    out["has_拍卖标的"] = "拍卖标的" in body
    out["has_标的物介绍"] = "标的物介绍" in body
    out["has_公告详情加载中"] = "公告详情加载中" in body
    return out


async def _run(headless: bool) -> int:
    from playwright.async_api import async_playwright
    from utils.browser import get_profile

    profile = get_profile()
    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            str(ALI.PROFILE_DIR), headless=headless, user_agent=profile["ua"],
            viewport={"width": 1366, "height": 900}, locale="zh-CN",
            timezone_id="Asia/Shanghai", args=ALI.LAUNCH_ARGS,
            ignore_default_args=["--enable-automation"],
        )
        page = browser.pages[0] if browser.pages else await browser.new_page()
        for item_id in SAMPLE_ITEMS:
            url = f"https://sf-item.taobao.com/sf_item/{item_id}.htm"
            print(f"\n=== {item_id} ===", flush=True)
            try:
                rpage = await ALI._open_detail_page(url, browser, page=page)
                info = await _inspect(rpage, item_id)
                for k, v in info.items():
                    print(f"  {k}: {v}", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"  ERROR: {e}", flush=True)
        await browser.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="探针阿里详情页是否有描述/属性")
    parser.add_argument("--headless", action="store_true", default=False,
                        help="无头模式(需已登录 profile)")
    args = parser.parse_args()
    return asyncio.run(_run(args.headless))


if __name__ == "__main__":
    sys.exit(main())