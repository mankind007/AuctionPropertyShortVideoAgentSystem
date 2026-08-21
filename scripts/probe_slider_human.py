"""人工参与探针: 测 4 个 STEALTH patch 组合下, 滑块能否被人工解决。

目标: 找出哪个 patch 组合会导致"出现滑块且人工也无法通过"。
对每个组合开一个浏览器 → 滑块出现 → 用户人工拖动 →
判定是否真正通过(URL 离开 punish/x5sec + 列表项>0)。

16 种组合(clean_cdp / patch_platform / patch_ua / patch_canvas 的真值表)。
默认跑 6 个代表性组合(全关/单开4/全开), --all 跑全部 16 个。

用法:
    python scripts/probe_slider_human.py --list                  # 列表页(默认, 易触发)
    python scripts/probe_slider_human.py --url <详情URL>         # 详情页
    python scripts/probe_slider_human.py --all                   # 全部 16 组合
    python scripts/probe_slider_human.py --combos 0 5 15         # 只测指定组合序号
    python scripts/probe_slider_human.py --wait 150              # 人工最长等待 150s/组合

判定"通过": 15s 内 URL 离开 punish/x5sec/login 且列表项 ≥1(详情页: 主图出现)。
注意: 必须 有头模式(headless 缺省), 每次窗口请人工拖动滑块。
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import itertools
import sys
import time
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
DETAIL_URL = "https://sf-item.taobao.com/sf_item/1075845060425.htm"

FLAG_NAMES = ["clean_cdp", "patch_platform", "patch_ua", "patch_canvas"]
ALL_COMBOS = [dict(zip(FLAG_NAMES, bits)) for bits in itertools.product([False, True], repeat=4)]
KEY_COMBOS = [0, 1, 2, 4, 8, 15]  # 全关 / 单开4 / 全开


async def _passed(page, is_list: bool) -> bool:
    """真正通过 = URL 离开风控 + 内容加载。"""
    try:
        if await ALI._url_blocked(page):
            return False
        if is_list:
            return await page.locator(ALI.XP_ITEM).count() > 0
        # 详情页: 主图缩略图出现
        return await page.locator(ALI.XP_IMG).count() > 0
    except Exception:  # noqa: BLE001
        return False


async def _probe_once(p, url: str, is_list: bool, wait_s: int, combo: dict) -> str:
    from utils.browser import get_profile, render_stealth_script

    profile = get_profile()
    label = "+".join(k for k, v in combo.items() if v) or "全关"
    print(f"  [combo {label}] 启动浏览器(UA={profile['ua'][:45]}…)…", flush=True)
    browser = await p.chromium.launch_persistent_context(
        str(ALI.PROFILE_DIR), headless=False, user_agent=profile["ua"],
        viewport={"width": 1366, "height": 900}, locale="zh-CN",
        timezone_id="Asia/Shanghai", args=ALI.LAUNCH_ARGS,
        ignore_default_args=["--enable-automation"],
    )
    t0 = time.time()
    try:
        page = browser.pages[0] if browser.pages else await browser.new_page()
        await page.set_extra_http_headers({"Accept-Language": "zh-CN,zh;q=0.9"})
        await page.add_init_script(render_stealth_script(profile, **combo))
        page.set_default_timeout(30000)
        await page.goto(url, timeout=60000)
        await page.wait_for_timeout(3000)

        def elapsed():
            return time.time() - t0

        # 无滑块直接过
        if not await ALI._still_blocked(page):
            ok = await _passed(page, is_list)
            status = "无滑块,直接正常" if ok else "无滑块但内容为空"
            print(f"  [combo {label}] {elapsed():5.0f}s {status}", flush=True)
            return status

        print(f"  [combo {label}] {elapsed():5.0f}s 出现滑块 → 请在窗口人工拖动"
              f"(最长 {wait_s}s)。拖过后若页面跳回原列表/加载出内容即为通过。",
              flush=True)
        waited = 0
        passed_once = False
        while waited < wait_s:
            await page.wait_for_timeout(3000)
            waited += 3
            if await _passed(page, is_list):
                passed_once = True
                print(f"  [combo {label}] {elapsed():5.0f}s 人工拖过后已通过(内容加载)✓",
                      flush=True)
                break
            # 未通过: 提示当前状态
            if waited % 30 == 0:
                url = page.url[:70]
                nc = await ALI._dom_blocked(page)
                print(f"  [combo {label}] {elapsed():5.0f}s 仍被挡(滑块={nc}, "
                      f"url={url})…", flush=True)
        if passed_once:
            return "人工可通过"
        # 人工拖过了但内容仍不加载(URL 离开 punish 但列表空)?
        if not await ALI._url_blocked(page):
            return "人工拖过滑块但内容未加载(URL已离开风控)"
        return f"人工也无法通过(超时 {wait_s}s, 仍在风控页)"
    except Exception as e:  # noqa: BLE001
        print(f"  [combo {label}] error({e})", flush=True)
        return f"error({e})"
    finally:
        await browser.close()


async def _run(url: str, is_list: bool, wait_s: int, combos: list[dict]) -> int:
    from playwright.async_api import async_playwright

    print(f"目标: {url} ({'列表页' if is_list else '详情页'})", flush=True)
    print(f"人工最长等待: {wait_s}s/组合, 组合数: {len(combos)}\n", flush=True)
    results = []
    async with async_playwright() as p:
        for i, combo in enumerate(combos, start=1):
            label = "+".join(k for k, v in combo.items() if v) or "全关"
            print(f"\n===== 组合 {i}/{len(combos)}: {label} =====", flush=True)
            r = await _probe_once(p, url, is_list, wait_s, combo)
            results.append((label, r))
    print("\n" + "=" * 60, flush=True)
    print(f"{'组合':<45} 结果", flush=True)
    print("-" * 60, flush=True)
    for label, r in results:
        print(f"{label:<45} {r}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="STEALTH patch 组合下人工滑块可解性探针")
    parser.add_argument("--url", type=str, default="", help="详情页 URL")
    parser.add_argument("--list", action="store_true", help="测列表页(默认详情页)")
    parser.add_argument("--wait", type=int, default=120, help="人工最长等待秒数(默认 120)")
    parser.add_argument("--all", action="store_true", help="跑全部 16 组合")
    parser.add_argument("--combos", type=int, nargs="+", default=None,
                        help="指定组合序号(0=全关, 1=clean_cdp, 2=platform, 4=ua, 8=canvas, 15=全开)")
    args = parser.parse_args()
    if args.combos is not None:
        combos = [ALL_COMBOS[i] for i in args.combos]
    elif args.all:
        combos = ALL_COMBOS
    else:
        combos = [ALL_COMBOS[i] for i in KEY_COMBOS]
    url = args.url or (LIST_URL if args.list else DETAIL_URL)
    return asyncio.run(_run(url, args.list, args.wait, combos))


if __name__ == "__main__":
    sys.exit(main())
