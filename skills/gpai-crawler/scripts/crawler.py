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
from pathlib import Path
from typing import List, Optional

from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.schemas.listing import GpaiCrawlResult, GpaiDetail, GpaiListing
from utils.browser import LAUNCH_ARGS, STEALTH_SCRIPT, UA
from utils.description import extract_auction_description
from utils.download import download_chunk
from utils.network import goto_with_retry
from utils.parsing import extract_time, item_url, now_iso, row_label, to_int_price

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


def _parse_listing(node) -> GpaiListing:
    """从单个 list-item 节点解析出房源结构化数据(同步;仅供契约测试喂假节点)。"""
    raw = {}

    title_el = node.locator(XP_TITLE).first
    title = title_el.inner_text().strip() if title_el.count() else ""
    raw["title"] = title

    href = title_el.get_attribute("href") if title_el.count() else None
    url = item_url(href) if href else ""
    m = re.search(r"Web_Item_ID=(\d+)", url)
    item_id = m.group(1) if m else ""

    start_price = 0.0
    ref_price = None
    ref_price_type = ""
    start_time = None
    rows = [r.strip() for r in node.locator(XP_INFOS).all_inner_texts()]

    for row in rows:
        label = row_label(row)
        if ("起拍价" in row or "起拍" in row or "最新价" in row or "最新" in row
                or "变卖价" in row or "变卖" in row):
            start_price = to_int_price(row) or 0.0
            raw["start_price"] = row
        elif ("评估价" in row or "评估" in row or "市场价" in row or "参考价" in row
                or "参考" in row):
            val = to_int_price(row)
            if val is not None:
                ref_price = val
                ref_price_type = label or "参考价"
                raw["ref_price"] = row
        elif "开始" in label or "开始" in row:
            start_time = extract_time(row)
            raw["start_time"] = row

    raw.setdefault("start_price", "")
    raw.setdefault("ref_price", "")
    raw.setdefault("start_time", "")

    return GpaiListing(
        title=title,
        url=url,
        item_id=item_id,
        category="房产",
        start_price=start_price,
        ref_price=ref_price,
        ref_price_type=ref_price_type,
        start_time=start_time,
        crawled_at=now_iso(),
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
        await goto_with_retry(page, f"{SEARCH_URL}?at={SEARCH_AT}&restate={restate}",
                              warn="gpai列表", wait_ms=1500)

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
                await goto_with_retry(
                    new_page,
                    f"{SEARCH_URL}?at={SEARCH_AT}&restate={restate}&Page={page_num}",
                    warn="gpai翻页", wait_ms=4000,
                )
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
                    url = item_url(href_attr) if href_attr else ""
                    m = re.search(r"Web_Item_ID=(\d+)", url)
                    item_id = m.group(1) if m else ""

                    start_price = 0.0
                    ref_price = None
                    ref_price_type = ""
                    start_time = None
                    info_els = await page.locator(f"{xpath_base}//div[@class='gpai-infos']/p").all()
                    for info_el in info_els:
                        row = (await info_el.inner_text()).strip()
                        label = row_label(row)
                        if ("起拍价" in row or "起拍" in row or "最新价" in row or "最新" in row
                                or "变卖价" in row or "变卖" in row):
                            start_price = to_int_price(row) or 0.0
                        elif ("评估价" in row or "评估" in row or "市场价" in row or "参考价" in row
                                or "参考" in row):
                            val = to_int_price(row)
                            if val is not None:
                                ref_price = val
                                ref_price_type = label or "参考价"
                        elif "开始" in label or "开始" in row:
                            start_time = extract_time(row)

                    listing = GpaiListing(
                        title=title,
                        url=url,
                        item_id=item_id,
                        category="房产",
                        start_price=start_price,
                        ref_price=ref_price,
                        ref_price_type=ref_price_type,
                        start_time=start_time,
                        crawled_at=now_iso(),
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


async def _open_detail_page(url: str, page):
    """打开子页并注入隐身脚,待主图加载;返回 page(由调用方负责关闭)。

    提供独立 page 上下文给 _fetch_images / _fetch_description 复用。
    """
    await goto_with_retry(page, url, warn="gpai子页", wait_ms=1500)
    await page.add_init_script(STEALTH_SCRIPT)
    await page.wait_for_selector(XP_IMG_REV, timeout=30000)
    return page


async def _fetch_images(page) -> List[str]:
    """抓取详情页图片链接(独立接口);rev 属性补 https: 前缀。"""
    revs = await page.eval_on_selector_all(
        XP_IMG_REV,
        "els => els.map(e => e.getAttribute('rev')).filter(Boolean)",
    )
    return ["https:" + r if not r.startswith("http") else r for r in revs]


async def _fetch_description(page) -> str:
    """抓取标的物描述(独立接口);无描述时返回空串。

    按 docs/初步信息 只提取「拍卖标的…」到最近章节标题「X、」之间的文字。
    """
    desc_el = page.locator("xpath=//div[@class='d-article']")
    if await desc_el.count():
        return extract_auction_description((await desc_el.first.inner_text()).strip())
    return ""


async def _fetch_property_info(page) -> dict:
    """抓取「标的物介绍」tab 的调查情况表/审批表, 拍扁为扁平 dict。

    定位: `d-article2` 中首个含「调查情况表/审批表/具体描述/面积」的块(排除竞买须知等)。
    无结构化表时返回 {}; 面积按「表内 → 公告段落 → 介绍段落」优先级解析。
    """
    from utils.description import extract_gpai_property_info

    blocks = page.locator("xpath=//div[contains(@class,'d-article2')]")
    intro_html = ""
    intro_text = ""
    n = await blocks.count()
    for i in range(n):
        blk = blocks.nth(i)
        try:
            txt = (await blk.inner_text()).strip()
        except Exception:  # noqa: BLE001
            continue
        if not txt or any(k in txt[:60] for k in ("竞买公告", "竞买须知", "重要提示", "竞买记录", "号牌")):
            continue
        if any(k in txt for k in ("调查情况表", "审批表", "具体描述", "标的物介绍", "面积")):
            intro_html = await blk.inner_html()
            intro_text = txt
            break
    announce_text = ""
    desc_el = page.locator("xpath=//div[@class='d-article']")
    if await desc_el.count():
        try:
            announce_text = (await desc_el.first.inner_text()).strip()
        except Exception:  # noqa: BLE001
            announce_text = ""
    return extract_gpai_property_info(intro_html, announce_text, intro_text)


async def _fetch_detail_impl(url: str) -> GpaiDetail:
    """抓取详情页: 主图 + 标的物描述(组合多个独立接口)。"""
    item_id = ""
    m = re.search(r"Web_Item_ID=(\d+)", url)
    if m:
        item_id = m.group(1)
    detail = GpaiDetail(item_id=item_id)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, args=LAUNCH_ARGS,
                                          ignore_default_args=["--enable-automation"])
        page = await browser.new_page()
        try:
            await _open_detail_page(url, page)
            detail.images = await _fetch_images(page)
            detail.description = await _fetch_description(page)
            detail.property_info = await _fetch_property_info(page)
        finally:
            await browser.close()
    return detail


def fetch_detail(url: str, headless: bool = True) -> GpaiDetail:
    """抓取详情页: 主图 + 标的物描述。"""
    return asyncio.run(_fetch_detail_impl(url))


async def _enrich_with_images_impl(result: GpaiCrawlResult, delay: float) -> None:
    """为结果中的每个房源抓取详情页图片链接(内部 async 实现)。"""
    for listing in result.listings:
        if not listing.url:
            continue
        try:
            d = await _fetch_detail_impl(listing.url)
            result.details.append(d)
            await asyncio.sleep(delay)
        except Exception as e:  # noqa: BLE001
            result.errors.append(f"detail {listing.url}: {e}")


def enrich_with_images(result: GpaiCrawlResult, headless: bool = True, delay: float = 0.3) -> None:
    """为结果中的每个房源抓取详情页图片链接。带间隔避免触发风控。"""
    asyncio.run(_enrich_with_images_impl(result, delay))


def download_images(detail: GpaiDetail, listing_id: str, assets_root: Path,
                    timeout: int = 30) -> List[dict]:
    """下载详情页图片到 assets/{listing_id}/imgs/,返回 [{url, file}] 结构。

    file: 本地文件名(含扩展名);下载失败为 None。已存在跳过(断点续跑),单张失败重试 3 次后置 None。
    按 3~5 张一批并发下载。同时把 detail.image_files 对齐填充。
    """
    target_dir = assets_root / str(listing_id) / "imgs"
    target_dir.mkdir(parents=True, exist_ok=True)
    pending: List[tuple] = []  # (dest, url, idx)
    for idx, img_url in enumerate(detail.images, start=1):
        ext = Path(img_url.split("?")[0]).suffix or ".jpg"
        pending.append((target_dir / f"{idx:02d}{ext}", img_url, idx))
    done: dict = {}
    todo: List[tuple] = []
    for dest, img_url, idx in pending:
        if dest.exists():
            done[idx] = {"url": img_url, "file": dest.name}
        else:
            todo.append((dest, img_url, idx))
    x = random.randint(3, 5)
    for i in range(0, len(todo), x):
        batch = todo[i:i + x]
        download_chunk([(d, u) for d, u, _ in batch], timeout)
        for d, u, idx in batch:
            done[idx] = {"url": u, "file": d.name if d.exists() else None}
    ordered: List[dict] = []
    for idx in range(1, len(detail.images) + 1):
        if idx in done:
            ordered.append(done[idx])
    detail.image_files = [x.get("file") for x in ordered]
    return ordered


async def _enrich_with_images_download_impl(result: GpaiCrawlResult, assets_root: Path,
                                            delay: float,
                                            known: Optional[dict] = None) -> None:
    """抓取详情页图片链接并下载(内部 async 实现);支持 DB 已知图清单的断点续传。

    known: {item_id: [{url,file}]} —— 已完整则跳过开子页;缺文件用 DB url 离线补下。
    """
    for listing in result.listings:
        if not listing.url:
            continue
        item_id = listing.item_id
        k = (known or {}).get(item_id)
        if k is not None:
            local = assets_root / item_id / "imgs"
            all_present = all(x.get("file") and (local / x["file"]).exists() for x in k)
            if all_present:
                result.details.append(GpaiDetail(item_id=item_id, images=[x["url"] for x in k],
                                                 image_files=[x.get("file") for x in k]))
                print(f"  [{item_id}] 已完整,跳过子页", flush=True)
                continue
            d = GpaiDetail(item_id=item_id, images=[x["url"] for x in k])
            download_images(d, item_id, assets_root)
            result.details.append(d)
            print(f"  [{item_id}] 离线补下(DB 已知)", flush=True)
            continue
        try:
            d = await _fetch_detail_impl(listing.url)
            download_images(d, item_id, assets_root)
            result.details.append(d)
            await asyncio.sleep(delay)
        except Exception as e:  # noqa: BLE001
            result.errors.append(f"detail {listing.url}: {e}")


def enrich_with_images_download(result: GpaiCrawlResult, assets_root: Path,
                                headless: bool = True, delay: float = 0.3,
                                known: Optional[dict] = None) -> None:
    """抓取详情页图片链接并下载到 assets/{listing_id}/imgs/。known: DB 已知图清单(断点续传)。"""
    asyncio.run(_enrich_with_images_download_impl(result, assets_root, delay, known=known))


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
    parser.add_argument("--assets-root", type=str, default=str(PROJECT_ROOT / "assets" / "gpai"),
                        help="assets 根目录(配合 --download,默认 assets/gpai)")
    parser.add_argument("--headless", action="store_true", default=True,
                        help="无头模式(默认 True)")
    parser.add_argument("--save-json", type=str, default="",
                        help="结果 JSON 输出路径(如 assets/gpai_result.json)")
    parser.add_argument("--db", action="store_true",
                        help="结果 upsert 进 PostgreSQL listings 表(见 .env DATABASE_URL;不可用时自动跳过)")
    parser.add_argument("--skip-complete", action="store_true",
                        help="断点续传(以 DB 为准): 已采完图的子页跳过,缺的文件离线补下")
    args = parser.parse_args()

    print(f"抓取列表页(即将开始): pages={args.pages} ...")
    result = fetch_listings(pages=args.pages, headless=args.headless)
    print(f"总数: {result.total}, 解析: {len(result.listings)} 条")

    if args.with_images:
        print("抓取详情页图片 ...")
        enrich_with_images(result)

    known = None
    src_data = {}
    if args.download:
        assets_root = Path(args.assets_root)
        if args.skip_complete:
            from db import get_source_data, get_source_images  # 懒加载

            known = get_source_images("gpai")
            src_data = get_source_data("gpai")
            print(f"  断点续传: DB 已采图 {len(known)} 条可跳过", flush=True)
        print(f"抓取并下载详情页图片到 {assets_root}/{{listing_id}}/imgs/ ...")
        enrich_with_images_download(result, assets_root, known=known)
        n = sum(len(d.images) for d in result.details)
        print(f"图片链接 {n} 张,详情条数 {len(result.details)}")

    if args.db:
        from db import upsert_listing  # 懒加载: DB 不可用时不影响采集

        print(f"-- 入库 {len(result.listings)} 条:")
        n_ok = n_fail = 0
        for l in result.listings:
            detail = next((d for d in result.details if d.item_id == l.item_id), None)
            # 标题变化 = 新数据 → data 清空重建;否则以 DB 旧 data 为底 merge,
            # 只覆盖本次抓到的字段,缺的(description 等)保留
            rec = (src_data or {}).get(l.item_id) or {}
            title_changed = bool(rec) and (rec.get("title") or "") != (l.title or "")
            old_data = dict(rec.get("data") or {}) if rec else {}
            data = {} if (title_changed or not old_data) else old_data
            images = []
            if detail and detail.image_files:
                images = [{"url": u, "file": f}
                          for u, f in zip(detail.images, detail.image_files)]
            elif detail and detail.images:
                images = [{"url": u, "file": None} for u in detail.images]
            elif known and (known.get(l.item_id)):
                images = known[l.item_id]
            data["images"] = images
            data["raw"] = {k: v for k, v in (l.raw or {}).items() if k not in ("href", "title")}
            if detail and detail.description:
                data["description"] = detail.description
            if detail and detail.property_info:
                data["property_info"] = detail.property_info
            if title_changed:
                data.pop("_empty", None)
            row = l.to_dict()
            row.pop("raw", None)
            row["data"] = data
            if upsert_listing(row):
                n_ok += 1
            else:
                n_fail += 1
        print(f"  -- 入库成功 {n_ok},失败 {n_fail}(DB 不可用会跳过,不影响采集)")

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
