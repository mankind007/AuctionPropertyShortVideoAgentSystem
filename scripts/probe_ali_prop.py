"""探针11: dump #J_DetailTabMain 下的表格内容(这3条只有 detail_tables=1)。"""
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


async def _run(item_id: str) -> int:
    from playwright.async_api import async_playwright
    from utils.browser import get_profile

    url = f"https://sf-item.taobao.com/sf_item/{item_id}.htm"
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
            rpage = await ALI._open_detail_page(url, browser, page=page)
            print(f"url={rpage.url[:80]}", flush=True)
            dump = await rpage.evaluate("""() => {
                const out = [];
                document.querySelectorAll('#J_DetailTabMain table, #J_NoticeDetail table').forEach((t,i)=>{
                    const trs = t.querySelectorAll('tr').length;
                    const text = (t.innerText||'').slice(0,150).replace(/\\n/g,' | ');
                    const chain=[]; let n=t;
                    for(let j=0;j<5&&n;j++){ chain.push((n.tagName||'').toLowerCase()+(n.id?('#'+n.id):'')+(n.className&&typeof n.className==='string'?('.'+n.className.split(' ')[0]):'')); n=n.parentElement; }
                    out.push({i, trs, text, chain:chain.join(' < ')});
                });
                return out;
            }""")
            for d in dump:
                print(f"table tr={d['trs']} head={d['text']!r}", flush=True)
                print(f"   chain: {d['chain']}", flush=True)
            # 全部 table
            all_t = await rpage.evaluate("""() => {
                return [...document.querySelectorAll('table')].map((t,i)=>({i, trs:t.querySelectorAll('tr').length, head:(t.innerText||'').slice(0,60).replace(/\\n/g,' | ')}));
            }""")
            print("all tables:", all_t, flush=True)
        finally:
            await browser.close()
    return 0


if __name__ == "__main__":
    item = sys.argv[1] if len(sys.argv) > 1 else "1071181323991"
    asyncio.run(_run(item))