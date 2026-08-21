"""诊断脚本: 打开阿里列表页, 打印真实滑块/验证 DOM 结构。

用途: 确认 _dom_blocked 的 #nc_1_* 选择器与实际滑块是否匹配,
以及滑块的真实形态(滑轨? iframe? 点选?), 用于修正检测逻辑。
"""
from __future__ import annotations

import asyncio
import importlib.util
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

LIST_URL = "https://sf.taobao.com/list/50025969__1.htm?auction_source=0&st_param=-1&auction_start_seg=-1"


async def main() -> int:
    from playwright.async_api import async_playwright
    from utils.browser import get_profile, render_stealth_script

    profile = get_profile()
    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            str(ALI.PROFILE_DIR), headless=False, user_agent=profile["ua"],
            viewport={"width": 1366, "height": 900}, locale="zh-CN",
            timezone_id="Asia/Shanghai", args=ALI.LAUNCH_ARGS,
            ignore_default_args=["--enable-automation"],
        )
        page = browser.pages[0] if browser.pages else await browser.new_page()
        await page.set_extra_http_headers({"Accept-Language": "zh-CN,zh;q=0.9"})
        await page.add_init_script(render_stealth_script(profile))
        page.set_default_timeout(30000)
        await page.goto(LIST_URL, timeout=60000)
        await page.wait_for_timeout(6000)

        print(f"URL: {page.url}", flush=True)
        print(f"dom_blocked (#nc_1_*): {await ALI._dom_blocked(page)}", flush=True)
        print(f"url_blocked (punish/x5sec/login): {await ALI._url_blocked(page)}", flush=True)

        # 1. 所有 id 含 nc / slider / captcha / verify 的元素
        print("\n--- 元素: id 含 nc/captcha/verify/slider ---", flush=True)
        info = await page.evaluate(
            """() => {
              const out = [];
              document.querySelectorAll('[id], [class]').forEach(el => {
                const id = el.id || '';
                const cls = typeof el.className === 'string' ? el.className : '';
                if (/(nc_|captcha|verify|slider|j_captcha|valid)/i.test(id + ' ' + cls)) {
                  out.push({id: id.slice(0, 60), cls: cls.slice(0, 60),
                            vis: el.offsetParent !== null,
                            tag: el.tagName});
                }
              });
              return out.slice(0, 40);
            }"""
        )
        for i in info:
            print(f"  {i}", flush=True)

        # 2. iframe 情况
        print("\n--- iframe ---", flush=True)
        frames = await page.evaluate(
            """() => Array.from(document.querySelectorAll('iframe')).map(f =>
                 ({src: (f.src||'').slice(0,100), id: f.id, cls: (f.className||'').slice(0,40)})
               )"""
        )
        for f in frames:
            print(f"  {f}", flush=True)

        # 3. body 文本前 400 字
        print("\n--- body 文本(前400字) ---", flush=True)
        text = await page.evaluate(
            "() => document.body ? document.body.innerText.replace(/\\n+/g,' ').slice(0,400) : ''"
        )
        print(f"  {text!r}", flush=True)

        # 4. 列表项计数
        print(f"\n--- 列表项 count: {await page.locator(ALI.XP_ITEM).count()} ---", flush=True)

        # 5. 等人工处理? 不, 诊断仅观察。等 10s 看滑块是否变化
        await page.wait_for_timeout(10000)
        print(f"\n10s 后 URL: {page.url}", flush=True)
        print(f"10s 后 dom_blocked: {await ALI._dom_blocked(page)}", flush=True)
        print(f"10s 后 列表项 count: {await page.locator(ALI.XP_ITEM).count()}", flush=True)

        await browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
