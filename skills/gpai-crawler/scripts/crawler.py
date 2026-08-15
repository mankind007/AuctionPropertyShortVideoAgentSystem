"""公拍网爬虫核心逻辑(列表页 + 详情页)。

可直接运行:
    python skills/gpai-crawler/scripts/crawler.py --pages=1 [--save-json]
也可作为模块被 scripts/crawl_gpai.py 与 tests 复用。

依赖: playwright(lxml 非必需)。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import List, Optional

from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.schemas.listing import GpaiCrawlResult, GpaiDetail, GpaiListing

# ---------------------------------------------------------------------------
# 页面地址与 XPath 规则(基准见 docs/初步信息.txt,此处为实测确认后的版本)
# playwright locator 对 `.//` 相对路径不自动识别,统一加 xpath= 前缀
# ---------------------------------------------------------------------------
SEARCH_URL = "https://s.gpai.net/sf/Search.do"
SEARCH_AT = 376
# 仅采集"即将开始"(restate=1)的标的
RESTATE_DEFAULT = 1

XP_TOTAL = "xpath=//div[@class='filtbar-l fl']/span/label"
# 只取第一个 main-col-list(真实列表);页面第二个同名的为推荐区块,须排除
XP_ITEM = "xpath=(//ul[contains(@class,'main-col-list')])[1]//div[contains(@class,'list-item')]"
XP_TITLE = "xpath=.//div[contains(@class,'item-tit')]/a"
XP_INFOS = "xpath=.//div[@class='gpai-infos']/p"
# 单页房源上限。docs 记录每页最多16,实测页面改版后第一页为20;超过上限即判定爬错(混入其他区块)
PAGE_CAP = 20
# 详情页图片链接片段(rev 属性,需加 https: 前缀)
XP_IMG_REV = "xpath=//ul[@class='small-pics clearfix']/li/a"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 反自动化识别: 关闭 automation 特性并去掉 playwright 默认识别的 --enable-automation
LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-dev-shm-usage",
]

# ---------------------------------------------------------------------------
# 反检测注入脚本(L1-L4): 页面加载前注入,patch 所有已知 CDP 泄漏点
# 注意: 必须用 IIFE 立即执行,`add_init_script` 不会调用裸 `() => {}` 函数表达式
# ---------------------------------------------------------------------------
STEALTH_SCRIPT = """
(() => {
  const spoof = () => {
    // L1: navigator.webdriver = true(由 WebDriver 设置) → 强制覆盖为 false
    Object.defineProperty(navigator, 'webdriver', {
      get: () => false,
      configurable: true, enumerable: true,
    });

    // L2: navigator.plugins(真实 Chrome 有 2-5 个) → 伪造为 Plugin 对象
    Object.defineProperty(navigator, 'plugins', {
      get: () => {
        const make = (name) => ({
          name, filename: 'internal-' + name + '.dll',
          description: 'Portable Document Format', length: 1,
          item: (i) => make(name), namedItem: () => make(name), refresh: () => {},
        });
        return [make('Chrome PDF Plugin'), make('Chrome PDF Viewer')];
      },
      configurable: true, enumerable: true,
    });

    // L2: window.chrome(真实 Chrome 有 runtime/app/loadTimes/csi) → 补全
    window.chrome = {
      runtime: {},
      app: {},
      loadTimes: function() {},
      csi: function() {},
      symbolicNames: function() {},
    };

    // L3: navigator.languages → 伪造中文语言列表
    Object.defineProperty(navigator, 'languages', {
      get: () => ['zh-CN', 'zh', 'en-US', 'en', 'zh-TW'],
      configurable: true, enumerable: true,
    });

    // L3: hardwareConcurrency / deviceMemory
    Object.defineProperty(navigator, 'hardwareConcurrency', {
      get: () => 8, configurable: true, enumerable: true,
    });
    Object.defineProperty(navigator, 'deviceMemory', {
      get: () => 8, configurable: true, enumerable: true,
    });

    // L4: WebGL vendor/renderer → 如果 headless 下读到虚拟 GPU 则用真实值兜底
    // 有头模式下 getParameter 返回真实值,无需 patch;headless 下保持默认即可

    // L4: Permissions.prototype.query → 伪造 notification 权限状态
    if (window.Permissions && window.Permissions.prototype) {
      const origQuery = window.Permissions.prototype.query;
      window.Permissions.prototype.query = function(query) {
        if (query.name === 'notifications') {
          return Promise.resolve({ state: Notification.permission === 'granted' ? 'granted' : 'denied' });
        }
        return origQuery.call(this, query);
      };
    }
  };

  // 立即执行(navigator/window 的 defineProperty 无需等待 DOM)
  spoof();
})();
"""


def _now_iso() -> str:
    """当前本地时间 ISO 格式(不含微秒),作为采集时间戳。"""
    import datetime

    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _to_int_price(text: str) -> Optional[float]:
    """把价格文本转成元。支持 百元/千元/万元/十万元/百万元/亿元/十亿元/百亿元/千亿元 等中文单位,容忍 ','。"""
    if not text:
        return None
    t = text.strip()
    # 提取数字 + 中文单位后缀(单位可为 元/百元/千元/万元/十万元/百万元/亿元... 任意组合)
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*([十百千万亿]*元?)?", t)
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "元").strip()
    mult = 1.0
    if unit:
        if "亿" in unit:
            mult *= 1e8
        if "万" in unit:
            mult *= 1e4
        if "千" in unit:
            mult *= 1e3
        if "百" in unit:
            mult *= 100
        if "十" in unit:
            mult *= 10
    return round(num * mult, 2)


def _extract_time(text: str) -> Optional[str]:
    """提取形如 '开始时间:2026-8-13 10:00:00' / '预计结束:2026-8-13 10:00:00' 的原始串。

    仅提取时间串本身,不区分开始/结束;区分由调用方按行标签处理。
    """
    if not text:
        return None
    t = text.strip()
    m = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s*\d{1,2}:\d{2}(?::\d{2})?)", t)
    return m.group(1) if m else None


def _item_url(fragment: str) -> str:
    """列表页链接片段('//www.gpai.net/sf/item2.do?Web_Item_ID=xxx')补全为完整 URL。"""
    if fragment.startswith("http"):
        return fragment
    return "https:" + fragment


def _row_label(text: str) -> str:
    """从数据行文本提取前导标签(如 '评估价：1,056,669元' → '评估价')。"""
    m = re.match(r"^\s*([^：:]+)[：:]", text)
    return m.group(1).strip() if m else ""


def _parse_listing(node) -> GpaiListing:
    """从单个 list-item 节点解析出房源结构化数据(同步;仅供契约测试喂假节点)。"""
    raw = {}

    title_el = node.locator(XP_TITLE).first
    title = title_el.inner_text().strip() if title_el.count() else ""
    raw["title"] = title

    href = title_el.get_attribute("href") if title_el.count() else None
    url = _item_url(href) if href else ""
    m = re.search(r"Web_Item_ID=(\d+)", url)
    item_id = m.group(1) if m else ""

    start_price = 0.0
    ref_price = None
    ref_price_type = ""
    start_time = None
    rows = [r.strip() for r in node.locator(XP_INFOS).all_inner_texts()]

    for row in rows:
        label = _row_label(row)
        if ("起拍价" in row or "起拍" in row or "最新价" in row or "最新" in row
                or "变卖价" in row or "变卖" in row):
            start_price = _to_int_price(row) or 0.0
            raw["start_price"] = row
        elif ("评估价" in row or "评估" in row or "市场价" in row or "参考价" in row
                or "参考" in row):
            val = _to_int_price(row)
            if val is not None:
                ref_price = val
                ref_price_type = label or "参考价"
                raw["ref_price"] = row
        elif "开始" in label or "开始" in row:
            start_time = _extract_time(row)
            raw["start_time"] = row

    raw.setdefault("start_price", "")
    raw.setdefault("ref_price", "")
    raw.setdefault("start_time", "")

    return GpaiListing(
        title=title,
        url=url,
        item_id=item_id,
        start_price=start_price,
        ref_price=ref_price,
        ref_price_type=ref_price_type,
        start_time=start_time,
        crawled_at=_now_iso(),
        status="",
        raw=raw,
    )


async def _fetch_listings_impl(pages: int) -> GpaiCrawlResult:
    """抓取即将开始(restate=1)列表页房源(内部 async 实现)。"""
    restate = RESTATE_DEFAULT
    result = GpaiCrawlResult(restate=restate, total=0)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=LAUNCH_ARGS,
                                          ignore_default_args=["--enable-automation"])
        page = await browser.new_page()
        await page.set_extra_http_headers({"Accept-Language": "zh-CN,zh;q=0.9"})
        await page.add_init_script(STEALTH_SCRIPT)
        await page.goto(f"{SEARCH_URL}?at={SEARCH_AT}&restate={restate}", timeout=30000)
        await page.wait_for_timeout(1500)

        total_el = page.locator(XP_TOTAL)
        if await total_el.count():
            text = (await total_el.first.inner_text()).strip()
            result.total = int(text or "0")
        else:
            result.total = 0

        total_pages = math.ceil(result.total / PAGE_CAP) if result.total else 1
        if pages > 0:
            total_pages = min(pages, total_pages)
        for page_num in range(1, total_pages + 1):
            if page_num > 1:
                if (page_num - 1) % 5 == 0:
                    await asyncio.sleep(random.uniform(3, 4))
                else:
                    await asyncio.sleep(random.uniform(0.5, 2.5))
                # 同 tab 内 goto(/&Page=N)会触发滑块验证,改为每页开新 tab 更稳定
                new_page = await browser.new_page()
                await new_page.set_extra_http_headers({"Accept-Language": "zh-CN,zh;q=0.9"})
                await new_page.add_init_script(STEALTH_SCRIPT)
                await new_page.goto(
                    f"{SEARCH_URL}?at={SEARCH_AT}&restate={restate}&Page={page_num}",
                    timeout=30000,
                )
                await new_page.wait_for_timeout(4000)
                await page.close()
                page = new_page
            count = await page.locator(XP_ITEM).count()
            if count > PAGE_CAP:
                result.errors.append(
                    f"单页条目 {count} 超过上限 {PAGE_CAP},可能混入推荐区块,请核对页面结构"
                )
            for i in range(count):
                try:
                    xpath_base = f"xpath=({XP_ITEM.lstrip('xpath=')})[{i + 1}]"
                    title_locator = page.locator(f"{xpath_base}//div[contains(@class,'item-tit')]/a")
                    title = (await title_locator.inner_text()).strip()
                    href_attr = await title_locator.get_attribute("href")
                    url = _item_url(href_attr) if href_attr else ""
                    m = re.search(r"Web_Item_ID=(\d+)", url)
                    item_id = m.group(1) if m else ""

                    start_price = 0.0
                    ref_price = None
                    ref_price_type = ""
                    start_time = None
                    info_els = await page.locator(f"{xpath_base}//div[@class='gpai-infos']/p").all()
                    for info_el in info_els:
                        row = (await info_el.inner_text()).strip()
                        label = _row_label(row)
                        if ("起拍价" in row or "起拍" in row or "最新价" in row or "最新" in row
                                or "变卖价" in row or "变卖" in row):
                            start_price = _to_int_price(row) or 0.0
                        elif ("评估价" in row or "评估" in row or "市场价" in row or "参考价" in row
                                or "参考" in row):
                            val = _to_int_price(row)
                            if val is not None:
                                ref_price = val
                                ref_price_type = label or "参考价"
                        elif "开始" in label or "开始" in row:
                            start_time = _extract_time(row)

                    listing = GpaiListing(
                        title=title,
                        url=url,
                        item_id=item_id,
                        start_price=start_price,
                        ref_price=ref_price,
                        ref_price_type=ref_price_type,
                        start_time=start_time,
                        crawled_at=_now_iso(),
                        status="",
                        raw={},
                    )
                    if listing.item_id:
                        result.listings.append(listing)
                except Exception as e:  # noqa: BLE001
                    result.errors.append(f"list item #{i}: {e}")
        await browser.close()
    return result


def fetch_listings(pages: int = 0, headless: bool = True) -> GpaiCrawlResult:
    """抓取即将开始(restate=1)列表页房源。pages: 0=自动(全部页), >0=最多N页。

    页数按 total / PAGE_CAP 自动取整计算。
    """
    return asyncio.run(_fetch_listings_impl(pages))


async def _fetch_detail_images_impl(url: str) -> GpaiDetail:
    """抓取详情页图片链接(内部 async 实现)。"""
    item_id = ""
    m = re.search(r"Web_Item_ID=(\d+)", url)
    if m:
        item_id = m.group(1)
    detail = GpaiDetail(item_id=item_id)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=LAUNCH_ARGS,
                                          ignore_default_args=["--enable-automation"])
        page = await browser.new_page()
        await page.goto(url, timeout=30000)
        await page.add_init_script(STEALTH_SCRIPT)
        await page.wait_for_timeout(1500)
        revs = await page.eval_on_selector_all(
            XP_IMG_REV,
            "els => els.map(e => e.getAttribute('rev')).filter(Boolean)",
        )
        detail.images = ["https:" + r if not r.startswith("http") else r for r in revs]
        await browser.close()
    return detail


def fetch_detail_images(url: str, headless: bool = True) -> GpaiDetail:
    """抓取详情页图片链接(rev 属性,补 https: 前缀)。"""
    return asyncio.run(_fetch_detail_images_impl(url))


async def _enrich_with_images_impl(result: GpaiCrawlResult, delay: float) -> None:
    """为结果中的每个房源抓取详情页图片链接(内部 async 实现)。"""
    for listing in result.listings:
        if not listing.url:
            continue
        try:
            d = await _fetch_detail_images_impl(listing.url)
            result.details.append(d)
            await asyncio.sleep(delay)
        except Exception as e:  # noqa: BLE001
            result.errors.append(f"detail {listing.url}: {e}")


def enrich_with_images(result: GpaiCrawlResult, headless: bool = True, delay: float = 0.3) -> None:
    """为结果中的每个房源抓取详情页图片链接。带间隔避免触发风控。"""
    asyncio.run(_enrich_with_images_impl(result, delay))


def download_images(detail: GpaiDetail, listing_id: str, assets_root: Path,
                    timeout: int = 30) -> List[str]:
    """下载详情页图片到 assets/{listing_id}/imgs/,返回本地路径列表。

    失败图片记入返回外的 errors 不在此处理,由调用方收集。
    """
    saved = []
    target_dir = assets_root / str(listing_id) / "imgs"
    target_dir.mkdir(parents=True, exist_ok=True)
    for idx, img_url in enumerate(detail.images, start=1):
        ext = Path(img_url.split("?")[0]).suffix or ".jpg"
        dest = target_dir / f"{idx:02d}{ext}"
        if dest.exists():
            saved.append(str(dest))
            continue
        req = urllib.request.Request(img_url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as f:
                f.write(resp.read())
            saved.append(str(dest))
        except Exception:  # noqa: BLE001
            continue
    return saved


async def _enrich_with_images_download_impl(result: GpaiCrawlResult, assets_root: Path,
                                             delay: float) -> None:
    """抓取详情页图片链接并下载到 assets/{listing_id}/imgs/(内部 async 实现)。"""
    await _enrich_with_images_impl(result, delay)
    for listing in result.listings:
        detail = next((d for d in result.details if d.item_id == listing.item_id), None)
        if detail and detail.images:
            try:
                download_images(detail, listing.item_id, assets_root)
            except Exception as e:  # noqa: BLE001
                result.errors.append(f"download {listing.item_id}: {e}")


def enrich_with_images_download(result: GpaiCrawlResult, assets_root: Path,
                                 headless: bool = True, delay: float = 0.3) -> None:
    """抓取详情页图片链接并下载到 assets/{listing_id}/imgs/。"""
    asyncio.run(_enrich_with_images_download_impl(result, assets_root, delay))


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    parser = argparse.ArgumentParser(description="公拍网房产列表爬虫(即将开始)")
    parser.add_argument("--pages", type=int, default=0,
                        help="抓取页数,0=自动(按总数/每页20计算全部页,默认 0)")
    parser.add_argument("--with-images", action="store_true", help="同时抓取详情页图片链接")
    parser.add_argument("--download", action="store_true",
                        help="抓取并下载详情页图片到 assets/{listing_id}/imgs/)")
    parser.add_argument("--assets-root", type=str, default="assets",
                        help="assets 根目录(配合 --download,默认 assets)")
    parser.add_argument("--headless", action="store_true", default=True,
                        help="无头模式(默认 True)")
    parser.add_argument("--save-json", type=str, default="",
                        help="结果 JSON 输出路径(如 assets/gpai_result.json)")
    args = parser.parse_args()

    print(f"抓取列表页(即将开始): pages={args.pages} ...")
    result = fetch_listings(pages=args.pages, headless=args.headless)
    print(f"总数: {result.total}, 解析: {len(result.listings)} 条")

    if args.with_images:
        print("抓取详情页图片 ...")
        enrich_with_images(result)

    if args.download:
        assets_root = Path(args.assets_root)
        print(f"抓取并下载详情页图片到 {assets_root}/{{listing_id}}/imgs/ ...")
        enrich_with_images_download(result, assets_root)
        n = sum(len(d.images) for d in result.details)
        print(f"图片链接 {n} 张,详情条数 {len(result.details)}")

    for l in result.listings:
        print(f"  [{l.item_id}] {l.title} | 起拍 {l.start_price} 元 | {l.ref_price_type or '参考价'} {l.ref_price} | 开始 {l.start_time} | 采集 {l.crawled_at}")

    if result.errors:
        print("\n错误:")
        for e in result.errors:
            print("  ", e)

    if args.save_json:
        Path(args.save_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.save_json).write_text(
            json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"已保存: {args.save_json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
