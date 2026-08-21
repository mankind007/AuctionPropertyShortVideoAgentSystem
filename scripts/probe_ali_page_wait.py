"""探针5: 有头 + _open_detail_page(自动拖滑块)打开页面。

加滚动/点击tab/长等待,确认公告与属性是否真的不渲染,还是只是时机问题。
"""
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


async def _run(item_id: str, total_s: int) -> int:
    from playwright.async_api import async_playwright
    from utils.browser import get_profile

    profile = get_profile()
    url = f"https://sf-item.taobao.com/sf_item/{item_id}.htm"
    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            str(ALI.PROFILE_DIR), headless=False, user_agent=profile["ua"],
            viewport={"width": 1366, "height": 900}, locale="zh-CN",
            timezone_id="Asia/Shanghai", args=ALI.LAUNCH_ARGS,
            ignore_default_args=["--enable-automation"],
        )
        page = browser.pages[0] if browser.pages else await browser.new_page()
        try:
            rpage = await ALI._open_detail_page(url, browser, page=page)
            print(f"url={rpage.url[:100]}", flush=True)
            nd = rpage.locator("xpath=//div[@id='J_NoticeDetail']")

            prev = ""
            for sec in range(0, total_s + 1, 5):
                txt = (await nd.first.inner_text()).strip() if await nd.count() else "<missing>"
                if txt != prev:
                    print(f"t={sec:3d}s notice_len={len(txt)} head={txt[:60]!r}", flush=True)
                    prev = txt
                if len(txt) > 13 and "加载" not in txt and "公告详情" not in txt:
                    print(">>> 公告真实内容已渲染!", flush=True)
                    break
                # 模拟滚动到底触发懒加载
                try:
                    await rpage.mouse.wheel(0, 3000)
                except Exception:  # noqa: BLE001
                    pass
                await rpage.wait_for_timeout(5000)

            # 阶段2: 找「标的物介绍」tab 并点击
            tab = rpage.locator(
                "xpath=//*[self::a or self::li or self::div][normalize-space()='标的物介绍']").first
            if await tab.count():
                try:
                    await tab.click(timeout=5000)
                    print(">>> 点击标的物介绍 tab", flush=True)
                    await rpage.wait_for_timeout(6000)
                except Exception as e:  # noqa: BLE001
                    print(f">>> 点击失败: {e}", flush=True)

            tables = rpage.locator("xpath=//table")
            n = await tables.count()
            print(f">>> 页面 table 总数: {n}", flush=True)
            for i in range(min(n, 5)):
                trs = await tables.nth(i).locator("xpath=.//tr").count()
                head = (await tables.nth(i).inner_text()).strip()[:150].replace("\n", " | ")
                print(f"    table[{i}] tr={trs} head={head!r}", flush=True)

            body = await rpage.locator("xpath=//body").inner_text()
            print("has_拍卖标的:", "拍卖标的" in body, "has_标的物属性:", "标的物属性" in body,
                  "has_起拍价:", "起拍价" in body, "body_len:", len(body), flush=True)
        finally:
            await browser.close()
    return 0


if __name__ == "__main__":
    item = sys.argv[1] if len(sys.argv) > 1 else "1074103694214"
    total = int(sys.argv[2]) if len(sys.argv) > 2 else 45
    asyncio.run(_run(item, total))