"""探针脚本: 对照测试 STEALTH_SCRIPT 四个可选 patch 哪个会触发阿里验证码。

对同一详情 URL,分别以以下配置启动浏览器检测滑块/惩罚页:
  1. 默认(4 个 patch 全关)
  2. +clean_cdp
  3. +patch_platform
  4. +patch_ua
  5. +patch_canvas
  6. 全开

每个配置用独立 UA(随机 profile),固定 headless=False(真实渲染)。
判据: URL 含 punish/x5sec/login 或 DOM 出现 #nc_1_* 滑块 → 判定"触发验证码"。
等待逻辑: goto 后最多等 25s, 每 2s 检测一次。

用法:
    python scripts/probe_stealth_params.py [--url https://sf-item.taobao.com/sf_item/XXXX.htm]
    python scripts/probe_stealth_params.py --headless
"""
from __future__ import annotations

import argparse
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

DEFAULT_URL = "https://sf-item.taobao.com/sf_item/1075845060425.htm"
LIST_URL = "https://sf.taobao.com/list/50025969__1.htm?auction_source=0&st_param=-1&auction_start_seg=-1"

COMBOS = [
    ("默认(全关)", dict()),
    ("+clean_cdp", dict(clean_cdp=True)),
    ("+patch_platform", dict(patch_platform=True)),
    ("+patch_ua", dict(patch_ua=True)),
    ("+patch_canvas", dict(patch_canvas=True)),
    ("全开", dict(clean_cdp=True, patch_platform=True, patch_ua=True, patch_canvas=True)),
]


async def _check_once(page) -> str:
    """返回检测状态: blocked(滑块/惩罚) / clean(正常) / error。"""
    try:
        if await ALI._still_blocked(page):
            url = page.url[:90]
            dom = await ALI._dom_blocked(page)
            return f"触发验证码 (dom={dom}, url={url})"
        return "正常"
    except Exception as e:  # noqa: BLE001
        return f"error({e})"


async def _run_one(p, url: str, headless: bool, label: str, kwargs: dict) -> str:
    from utils.browser import get_profile, render_stealth_script

    profile = get_profile()
    browser = await p.chromium.launch_persistent_context(
        str(ALI.PROFILE_DIR), headless=headless, user_agent=profile["ua"],
        viewport={"width": 1366, "height": 900}, locale="zh-CN",
        timezone_id="Asia/Shanghai", args=ALI.LAUNCH_ARGS,
        ignore_default_args=["--enable-automation"],
    )
    try:
        page = browser.pages[0] if browser.pages else await browser.new_page()
        await page.set_extra_http_headers({"Accept-Language": "zh-CN,zh;q=0.9"})
        await page.add_init_script(render_stealth_script(profile, **kwargs))
        page.set_default_timeout(30000)
        await page.goto(url, timeout=60000)
        # 最多等 25s,每 2s 检测滑块
        status = "正常"
        for _ in range(13):
            await page.wait_for_timeout(2000)
            status = await _check_once(page)
            if "触发" in status:
                break
        return status
    except Exception as e:  # noqa: BLE001
        return f"error({e})"
    finally:
        await browser.close()


async def _run(url: str, headless: bool) -> int:
    from playwright.async_api import async_playwright

    print(f"目标 URL: {url}", flush=True)
    print(f"headless={headless}, 检测窗口 25s/配置\n", flush=True)
    results = []
    async with async_playwright() as p:
        for label, kwargs in COMBOS:
            print(f"[{label}] 启动…", flush=True)
            status = await _run_one(p, url, headless, label, kwargs)
            results.append((label, status))
            print(f"[{label}] -> {status}\n", flush=True)
    print("=" * 50, flush=True)
    for label, status in results:
        print(f"{label}: {status}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="STEALTH patch 触发验证码对照测试")
    parser.add_argument("--url", type=str, default="", help="阿里详情 URL")
    parser.add_argument("--list", action="store_true", help="测试列表页(更易触发滑块)")
    parser.add_argument("--headless", action="store_true", help="无头模式(不推荐,行为风控差异大)")
    args = parser.parse_args()
    url = args.url or (LIST_URL if args.list else DEFAULT_URL)
    return asyncio.run(_run(url, args.headless))


if __name__ == "__main__":
    sys.exit(main())
