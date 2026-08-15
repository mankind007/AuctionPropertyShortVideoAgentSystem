"""公拍网翻页滑块验证观测脚本(人工运行)。

用途: 人工在浏览器窗口中观察点击"第 2 页"后是否触发滑块验证,
用于确认反爬机制(The page may show "Slide jigsaw to complete verification")。

用法:
    python scripts/observe_gpai_pagination.py                 # 默认 restate=1(即将开始)
    python scripts/observe_gpai_pagination.py --restate=2     # 正在拍卖
    python scripts/observe_gpai_pagination.py --hold=40       # 停留40秒(默认25)

注意: 必须带窗口运行(--headful 默认开启),无头模式看不到滑块。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import importlib.util  # noqa: E402
import playwright.sync_api as pw  # noqa: E402


def _load_crawler():
    mod_path = PROJECT_ROOT / "skills" / "gpai-crawler" / "scripts" / "crawler.py"
    spec = importlib.util.spec_from_file_location("gpai_crawler", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def first_ul_item_count(page) -> int:
    return page.evaluate(
        """() => {
            const u = document.querySelector("ul.main-col-list");
            return u ? u.querySelectorAll(".list-item").length : -1;
        }"""
    )


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="公拍网翻页滑块验证观测(人工在窗口观察)")
    parser.add_argument("--restate", type=int, default=1, choices=[1, 2],
                        help="1=即将开始(默认), 2=正在拍卖")
    parser.add_argument("--page", type=int, default=2, help="翻到第几页(默认 2)")
    parser.add_argument("--hold", type=int, default=25,
                        help="点击后停留秒数供人工观察(默认 25)")
    args = parser.parse_args()

    cr = _load_crawler()
    url = f"{cr.SEARCH_URL}?at={cr.SEARCH_AT}&restate={args.restate}"

    with pw.sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # 有头模式,弹窗口
        page = browser.new_page(user_agent=cr.UA)
        print(f"打开: {url}", flush=True)
        page.goto(url, timeout=30000)
        page.wait_for_timeout(2000)

        n1 = first_ul_item_count(page)
        print(f"第1页 .list-item 数量: {n1}", flush=True)
        if n1 <= 0:
            print("未找到列表,页面可能已经弹验证,请核对。", flush=True)
            page.wait_for_timeout(3000)
            browser.close()
            return 1

        selector = f'.page-nav a[href*="Page={args.page}"]'
        count = page.locator(selector).count()
        print(f"分页链接 [第{args.page}页] 存在: {count} 个 (#{selector})", flush=True)
        if count == 0:
            print("未找到该分页链接,请核对页面结构。", flush=True)
            page.wait_for_timeout(3000)
            browser.close()
            return 1

        page.locator(selector).first.click()
        page.wait_for_timeout(6000)
        print(f"点击后 URL: {page.url}", flush=True)

        body = page.evaluate("() => document.body ? document.body.innerText.slice(0, 160) : ''")
        print(f"页面文本前160字: {body.strip()!r}", flush=True)

        is_captcha = "verification" in body.lower() or "验证" in body
        print(
            "\n判定: " + ("检测到滑块验证字样(反爬拦截)。" if is_captcha else "未直接命中验证字样,请看看窗口实际内容。"),
            flush=True,
        )
        print(f"== 请在浏览器窗口中人工确认后,脚本 {args.hold}s 后自动关闭 ==", flush=True)
        page.wait_for_timeout(args.hold * 1000)
        browser.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())