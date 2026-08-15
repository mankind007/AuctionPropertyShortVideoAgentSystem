"""阿里资产(淘宝司法拍卖)爬虫核心逻辑(列表页 + 缩略图)。

可直接运行:
    python skills/ali-assets-crawler/scripts/crawler.py --category 住宅 --pages 2
也可作为模块被 scripts/crawl_ali.py 与 tests 复用。

要点:
- sf.taobao.com **强制登录**: 首次请用有头模式,弹出窗口人工登录/滑条,
  登录态会自动持久化到 profile(assets/ali/chrome_profile) 与
  storage_state(assets/ali/login_state.json),后续复用。
- 分页通过 URL `&page=N`;总页数取自 `//em[@class='page-total']`。
- 仅采集"即将开始"(`__1.htm`)的标的。
"""
from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import random
import re
import sys
from pathlib import Path
from typing import List, Optional

from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.schemas.listing import AuctionCrawlResult, AuctionDetail, AuctionListing
from utils.browser import LAUNCH_ARGS, STEALTH_SCRIPT, UA
from utils.download import download_chunk
from utils.network import REFRESH_INTERVAL_S, goto_with_retry
from utils.parsing import item_url, now_iso, to_int_price

# ---------------------------------------------------------------------------
# 分类与 URL(均可) — "即将开始"列表,分页用 &page=N
# ---------------------------------------------------------------------------
CATEGORIES = {
    # docs/初步信息.txt: 住宅用房 即将开始
    "住宅": "https://sf.taobao.com/list/50025969__1.htm?auction_source=0&st_param=-1&auction_start_seg=-1",
    # 商业用房
    "商业": "https://sf.taobao.com/list/200782003__1.htm?auction_source=0&st_param=-1&auction_start_seg=-1",
    # 工业用房
    "工业": "https://sf.taobao.com/list/200788003__1.htm?auction_source=0&st_param=-1&auction_start_seg=-1",
    # 其他用房
    "其他": "https://sf.taobao.com/list/200798003__1.htm?auction_source=0&st_param=-1&auction_start_seg=-1",
}

# 每个分类至少爬取的页数(人工约定)
MIN_PAGES = 2

# 资产根目录(profile / login_state / 下载目录都放这里)
DEFAULT_ASSETS = PROJECT_ROOT / "assets" / "ali"
PROFILE_DIR = DEFAULT_ASSETS / "chrome_profile"
LOGIN_STATE = DEFAULT_ASSETS / "login_state.json"

# ---------------------------------------------------------------------------
# XPath(基准见 docs/初步信息.txt;playwright 统一加 xpath= 前缀)
# ---------------------------------------------------------------------------
XP_PAGE_TOTAL = "xpath=//em[@class='page-total']"
XP_ITEM = "xpath=//div[@class='sf-item-list']/ul[@class='sf-pai-item-list'][1]/li"
# 注意: header-section 类名带尾空格,用 contains 匹配;标题在 p.title 内
XP_TITLE = "xpath=.//a/div[contains(concat(' ',@class,' '),' header-section')]/p[contains(@class,'title')]"
XP_ITEM_HREF = "xpath=./a"
# 起拍价 span.value(price-todo);参考价 span.value(price-assess)
XP_START_PRICE = "xpath=.//div[contains(@class,'info-section')]/p[contains(@class,'price-todo')]//span[contains(@class,'value')]"
XP_REF_PRICE = "xpath=.//div[contains(@class,'info-section')]/p[contains(@class,'price-assess')]//span[contains(@class,'value')]"
# 开始时间 span.value(time-todo),格式如 08月15日 10:00(需补当年,见 docs/初步信息.txt 第59行)
XP_START_TIME = "xpath=.//div[contains(@class,'info-section')]/p[contains(@class,'time-todo')]//span[contains(@class,'value')]"
# 详情页主图轮播(ul.pm-thumb 内 img;需加 https:// 前缀 + _80x80→_960x960)
XP_IMG = "xpath=//ul[contains(concat(' ',@class,' '),' pm-thumb')]//img"

# ---------------------------------------------------------------------------
# 纯函数(可测)
# ---------------------------------------------------------------------------


def _parse_ali_start_time(text: str) -> Optional[str]:
    """解析阿里列表页开始时间文本,如 '08月15日 10:00' → 当年 '2026-08-15 10:00'。

    格式来自 docs/初步信息.txt 第59行(p.time-todo > span.value)。
    补当年: 跨年(如 12月31日 23:55)解析为当年,若当年已过则视为次年。
    """
    if not text:
        return None
    m = re.match(r"\s*(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})", text)
    if not m:
        return None
    month, day, hour, minute = map(int, m.groups())
    year = datetime.date.today().year
    try:
        dt = datetime.datetime(year, month, day, hour, minute)
    except ValueError:
        return None
    # 已过(如今天已 12月31日 23:55+,该场次属于次年): 不深究,临界提醒由调用方做
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _is_near_midnight_deadline(text: str) -> bool:
    """检查开始时间是否落在 12月31日 23:55~24:00 区间(跨年临界提醒,见需求)。"""
    m = re.match(r"\s*(\d{1,2})月(\d{1,2})日\s+(\d{1,2}):(\d{2})", text or "")
    if not m:
        return False
    month, day, hour, minute = map(int, m.groups())
    return month == 12 and day == 31 and (hour == 23 and minute >= 55)


def _fix_img_src(src: str) -> str:
    """封面图 src → 高清 URL: 加 https:// 前缀 + 尺寸后缀归一为 _960x960。"""
    if not src:
        return ""
    url = src if src.startswith("http") else "https:" + src
    url = re.sub(r"_\d+x\d+(\.\w+)?$", r"_960x960\1", url)
    return url


def _extract_item_id(url: str) -> str:
    """从商品链接提取 id(阿里资产 sf_item 链接: /sf_item/{id}.htm 或 id= 参数)。"""
    m = re.search(r"[?&]id=(\d+)", url)
    if m:
        return m.group(1)
    m = re.search(r"/sf_item/(\d+)", url)
    return m.group(1) if m else ""


def _parse_listing(node, category: str) -> AuctionListing:
    """从单个 li 节点解析出房源(同步;仅供契约测试喂假节点)。

    真实抓取走 `_fetch_category_impl` 里的异步路径,此函数保证与异步版同结构。
    注: 图片在详情页采集,列表页只解析元数据。
    """
    title_el = node.locator(XP_TITLE).first
    title = title_el.inner_text().strip() if title_el.count() else ""

    href_el = node.locator(XP_ITEM_HREF).first
    href = href_el.get_attribute("href") if href_el.count() else ""
    url = item_url(href)
    item_id = _extract_item_id(url)

    start_price = 0.0
    sp_el = node.locator(XP_START_PRICE).first
    if sp_el.count():
        start_price = to_int_price(sp_el.inner_text()) or 0.0

    ref_price = None
    ref_price_type = ""
    ref_el = node.locator(XP_REF_PRICE).first
    if ref_el.count():
        v = to_int_price(ref_el.inner_text())
        if v is not None:
            ref_price = v
            ref_price_type = "参考价"

    start_time = None
    st_el = node.locator(XP_START_TIME).first
    if st_el.count():
        st_text = st_el.inner_text()
        start_time = _parse_ali_start_time(st_text)
        if _is_near_midnight_deadline(st_text):
            print(f"  ! 接近跨年临界: 标题={title!r}, 开始时间文本={st_text!r}", flush=True)

    return AuctionListing(
        source="ali",
        category=category,
        title=title,
        url=url,
        item_id=item_id,
        start_price=start_price,
        ref_price=ref_price,
        ref_price_type=ref_price_type,
        start_time=start_time,
        crawled_at=now_iso(),
        status="即将开始",
        raw={"href": href or "", "title": title},
    )


async def _dom_blocked(page) -> bool:
    """滑块 DOM 是否在页面上(#nc_1_* = 阿里滑块)。"""
    try:
        return await page.locator("#nc_1__scale_text, #nc_1_nz1").count() > 0
    except Exception:  # noqa: BLE001
        return False


async def _url_blocked(page) -> bool:
    u = page.url
    return "punish" in u or "x5sec" in u or "login.taobao.com" in u


async def _still_blocked(page) -> bool:
    if await _url_blocked(page):
        return True
    return await _dom_blocked(page)


async def _try_auto_slide(page, max_attempts: int = 2) -> bool:
    """尝试自动拖动阿里滑块(#nc_1_nz1 把手 → 右端)。成功返回 True;失败/无滑块返回 False。

    步骤: 拿到把手与滑轨 bounding box,鼠标按下把手中心,按缓动曲线分步移动(带随机抖动),
    松手后检测是否已通过。
    """
    for _ in range(max_attempts):
        if not await _dom_blocked(page):
            return True
        handle = page.locator("#nc_1_nz1")
        track = page.locator("#nc_1__scale_text")
        if not await handle.count() or not await track.count():
            return False
        hb = await handle.bounding_box()
        tb = await track.bounding_box()
        if not hb or not tb:
            return False
        start_x = hb["x"] + hb["width"] / 2
        y = hb["y"] + hb["height"] / 2
        distance = max(10.0, (tb["x"] + tb["width"] - hb["x"] - hb["width"] / 2) - 4)
        await page.mouse.move(start_x, y, steps=random.randint(4, 8))
        await page.wait_for_timeout(random.randint(150, 400))
        await page.mouse.down()
        # 缓动曲线: 前快后慢 + 随机抖动/停顿,模拟人手
        n_steps = random.randint(18, 26)
        for i in range(1, n_steps + 1):
            progress = i / n_steps
            eased = 1 - (1 - progress) ** 2
            cur_x = start_x + distance * eased + random.uniform(-1.2, 1.2)
            await page.mouse.move(cur_x, y + random.uniform(-1.0, 1.0), steps=1)
            if i % 7 == 0:
                await page.wait_for_timeout(random.randint(30, 90))
        await page.mouse.move(start_x + distance + random.uniform(0, 2), y, steps=2)
        await page.wait_for_timeout(random.randint(100, 250))
        await page.mouse.up()
        await page.wait_for_timeout(1500)
        if not await _still_blocked(page):
            return True
    return False


async def _wait_human_for_challenge(page, back_url: str, timeout_s: int = 300,
                                    label: str = "") -> bool:
    """检测列表页/详情页是否触发登录/滑块/风控。

    判定方式(URL + DOM 双通道):
    - URL: punish / x5sec / login.taobao.com
    - DOM: #nc_1__scale_text(整条滑轨) / #nc_1_nz1(滑块把手)
    处理流程:
    - 先自动拖滑块(#nc_1_*)1-2 次,成功即继续;
    - 自动失败了才转人工: 登录/断网每 5 分钟自动 goto 刷新;滑块未解随机 5-10 分钟刷新,
      并持续提示人工在弹出窗口验证。
    处理完成(URL 离开验证页 且 DOM 无滑块)立即返回,无需等满。
    返回 True = 已离开验证页,可继续。
    """
    if not await _still_blocked(page):
        return True
    if await _try_auto_slide(page):
        print(f"  {label}滑块已自动拖动通过,继续…", flush=True)
        return True
    waited = 0
    while waited < timeout_s:
        if not await _still_blocked(page):
            print(f"  {label}验证已人工完成,自动继续…", flush=True)
            return True
        print(f"  {label}自动拖滑块未通过,请在弹出窗口手动验证(最长等待 {timeout_s}s)…",
              flush=True)
        await page.wait_for_timeout(5000)
        waited += 5
        # 每 10 分钟自动 goto 刷新,维持登录会话/重试;滑块未解则随机 5-10 分钟刷新
        if waited % REFRESH_INTERVAL_S == 0 or random.random() < 0.05:
            try:
                await page.goto(back_url, timeout=45000)
                await page.wait_for_timeout(2000)
            except Exception:  # noqa: BLE001
                pass
    print(f"  ! {label}等待 {timeout_s}s 超时,仍未通过验证({page.url[:80]})", flush=True)
    return False


async def _fetch_detail_images(url: str, browser) -> AuctionDetail:
    """打开单个子页(详情页)采集主图轮播链接(内部 async 实现)。

    goto 用 domcontentloaded 避免 load 超时;pm-thumb 内 img 加 https:// + _960x960。
    触发滑块/风控时等待人工处理(最多 5 分钟,提前完成即继续)。
    """
    item_id = _extract_item_id(url)
    detail = AuctionDetail(source="ali", item_id=item_id)
    page = await browser.new_page()
    try:
        await page.set_extra_http_headers({"Accept-Language": "zh-CN,zh;q=0.9"})
        await page.add_init_script(STEALTH_SCRIPT)
        await goto_with_retry(page, url, timeout=60000, warn="ali子页", wait_ms=2500)
        while True:
            if not await _wait_human_for_challenge(page, url, label="子页"):
                break
            srcs = await page.eval_on_selector_all(
                XP_IMG,
                "els => els.map(e => e.getAttribute('src') || e.getAttribute('data-src')).filter(Boolean)",
            )
            if srcs:
                detail.images = [_fix_img_src(s) for s in srcs]
                break
            # 已在目标页但主图还没加载/被拦(可能刚解决验证页面正的回到详情),再短暂等待重试
            if "punish" in page.url or "x5sec" in page.url or "login.taobao.com" in page.url:
                continue
            await page.wait_for_timeout(2000)
    finally:
        await page.close()
    return detail


async def _fetch_category_impl(category: str, pages: int, headless: bool,
                               profile_dir: Path, login_state: Path,
                               assets_root: Path = DEFAULT_ASSETS,
                               with_images: bool = False,
                               skip_complete_images: Optional[dict] = None) -> AuctionCrawlResult:
    """抓取单个分类列表页房源(内部 async 实现)。with_images: 是否打开详情页采集图片。

    skip_complete_images: {item_id: [{url,file}]} —— DB 已采图清单,用于断点续传跳过/离线补下。
    """
    base_url = CATEGORIES[category]
    result = AuctionCrawlResult(source="ali", category=category, total=0)
    profile_dir.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            str(profile_dir), headless=headless, user_agent=UA,
            viewport={"width": 1366, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            color_scheme="light",
            args=LAUNCH_ARGS,
            ignore_default_args=["--enable-automation"],
        )
        page = browser.pages[0] if browser.pages else await browser.new_page()
        await page.set_extra_http_headers({"Accept-Language": "zh-CN,zh;q=0.9"})
        await page.add_init_script(STEALTH_SCRIPT)
        page.set_default_timeout(30000)

        print(f"\n[{category}] 打开: {base_url}", flush=True)
        await goto_with_retry(page, base_url, warn="ali列表", wait_ms=2500)

        # 鉴权等待: 登录页(login.taobao.com)、风控滑块(punish)、滑块 DOM(#nc_1_*)都需人工处理
        # 滑块/登录解决后页面会自动跳回列表;最多等待 5 分钟,登录期间每 5 分钟自动刷新
        item_count = await page.locator(XP_ITEM).count()
        waited = 0
        MAX_WAIT_S = 300
        while item_count == 0 and waited < MAX_WAIT_S:
            await _wait_human_for_challenge(page, base_url, timeout_s=60, label="主列表")
            print(f"  列表加载中(条目 {item_count})… {page.url[:80]}", flush=True)
            await page.wait_for_timeout(5000)
            # 登录/滑块解决后页面会跳回真实列表 URL;重新 goto 保证拿到列表
            if item_count == 0 and ("punish" in page.url or "login.taobao.com" in page.url):
                await page.goto(base_url, timeout=45000)
            await page.wait_for_timeout(2000)
            item_count = await page.locator(XP_ITEM).count()
            waited += 7
        if item_count == 0:
            url_now = page.url[:120]
            body_snip = (await page.evaluate(
                "() => document.body ? document.body.innerText.slice(0, 200) : ''"
            )).strip()
            print(f"  仍无列表项,当前 URL: {url_now}", flush=True)
            print(f"  页面文本前200字: {body_snip!r}", flush=True)
            result.errors.append(f"{category}: 鉴权后仍未取到列表项(URL={url_now})")
        await browser.storage_state(path=str(login_state))

        # 总页数
        total_pages = 1
        pt_els = page.locator(XP_PAGE_TOTAL)
        if await pt_els.count():
            txt = (await pt_els.first.inner_text()).strip()
            total_pages = int(re.sub(r"\D", "", txt) or "1")
        result.total = total_pages
        need = max(pages, MIN_PAGES) if pages > 0 else total_pages
        total_pages = min(total_pages, need)
        print(f"[{category}] 总页数(声明): {result.total}, 本次抓取: {total_pages} 页", flush=True)

        for page_num in range(1, total_pages + 1):
            if page_num > 1:
                await asyncio.sleep(1.5)
                await goto_with_retry(page, f"{base_url}&page={page_num}", warn="ali翻页", wait_ms=2500)
                if await page.locator(XP_ITEM).count() == 0:
                    result.errors.append(f"{category} 第{page_num}页为空(可能翻页受限),跳出")
                    break
            print(f"[{category}] 解析第 {page_num} 页 …", flush=True)
            items = page.locator(XP_ITEM)
            n = await items.count()
            page_listings = []
            for i in range(n):
                try:
                    item = items.nth(i)
                    title_el = item.locator(XP_TITLE).first
                    title = (await title_el.inner_text()).strip() if await title_el.count() else ""
                    href_el = item.locator(XP_ITEM_HREF).first
                    href = await href_el.get_attribute("href") if await href_el.count() else ""
                    url = item_url(href)
                    item_id = _extract_item_id(url)

                    sp = 0.0
                    sp_el = item.locator(XP_START_PRICE).first
                    if await sp_el.count():
                        sp = to_int_price(await sp_el.inner_text()) or 0.0

                    ref_price = None
                    ref_type = ""
                    ref_el = item.locator(XP_REF_PRICE).first
                    if await ref_el.count():
                        v = to_int_price(await ref_el.inner_text())
                        if v is not None:
                            ref_price = v
                            ref_type = "参考价"

                    start_time = None
                    st_el = item.locator(XP_START_TIME).first
                    if await st_el.count():
                        st_text = await st_el.inner_text()
                        start_time = _parse_ali_start_time(st_text)
                        if _is_near_midnight_deadline(st_text):
                            print(f"  ! 接近跨年临界: 标题={title!r}, 开始时间文本={st_text!r}",
                                  flush=True)

                    listing = AuctionListing(
                        source="ali",
                        category=category,
                        title=title,
                        url=url,
                        item_id=item_id,
                        start_price=sp,
                        ref_price=ref_price,
                        ref_price_type=ref_type,
                        start_time=start_time,
                        crawled_at=now_iso(),
                        status="即将开始",
                        raw={"href": href or "", "title": title},
                    )
                    if listing.item_id:
                        result.listings.append(listing)
                        result.details.append(AuctionDetail(source="ali", item_id=listing.item_id))
                        page_listings.append(listing)
                except Exception as e:  # noqa: BLE001
                    result.errors.append(f"{category} page{page_num} item#{i}: {e}")

            # 抓完本页主页数据后,立即依次打开本页所有子页抓图片,再翻下一页
            if with_images and page_listings:
                print(f"[{category}] 第 {page_num} 页: 抓取 {len(page_listings)} 个子页图片 …", flush=True)
                for j, listing in enumerate(page_listings, start=1):
                    # 每个子页打开前随机等待 0.5~2s;每 5 个子页额外 2~3.5s
                    await asyncio.sleep(random.uniform(0.5, 2.0))
                    if j % 5 == 0:
                        await asyncio.sleep(random.uniform(2.0, 3.5))
                    detail = next((d for d in result.details if d.item_id == listing.item_id), None)
                    if not detail:
                        continue
                    # 断点续传(以 DB 为准): 已知图清单里该 id 已采且本地齐全 → 跳过开子页
                    known = skip_complete_images.get(listing.item_id) if skip_complete_images else None
                    if known is not None and len(known) == len(detail.images) and all(
                            f and (assets_root / listing.item_id / "imgs" / f).exists()
                            for f in [x.get("file") for x in known]):
                        print(f"  [{page_num}.{j}] {listing.item_id} 已完整,跳过子页", flush=True)
                        continue
                    # 已知该 id 但本地缺文件/失败 → 用 DB 里的 url 离线补下,不再开浏览器
                    if known:
                        detail.images = [x["url"] for x in known]
                        files = download_images(detail, listing.item_id, assets_root)
                        print(f"  [{page_num}.{j}] {listing.item_id} 离线补下 {len([f for f in files if f.get('file')])} 张", flush=True)
                        continue
                    try:
                        d = await _fetch_detail_images(listing.url, browser)
                        detail.images = d.images
                        structured = _save_listing(listing, d, assets_root)
                        print(f"  [{page_num}.{j}] {listing.item_id} 图片 {len(d.images)} 张,"
                              f" 已存 {len([f for f in structured if f.get('file')])} 张", flush=True)
                    except Exception as e:  # noqa: BLE001
                        result.errors.append(f"detail {listing.url}: {e}")
        await browser.close()
    return result


def fetch_listings(category: str, pages: int = 2, headless: bool = False,
                   profile_dir: Path = PROFILE_DIR,
                   login_state: Path = LOGIN_STATE,
                   assets_root: Path = DEFAULT_ASSETS,
                   with_images: bool = False,
                   skip_complete_images: Optional[dict] = None) -> AuctionCrawlResult:
    """抓取阿里资产单个分类"即将开始"房源。

    category: 住宅/商业/工业/其他
    pages: 抓取页数,默认 2(至少 MIN_PAGES);0=全部页。
    headless: 默认 False(有头),首次必须;遇到滑块需人工拖动验证后才可复用。
    assets_root: 图片下载 + meta 落盘根目录(默认 assets/ali)。
    with_images: 为 True 时逐个打开子页采集图片(会较慢)。
    skip_complete_images: DB 已采图清单 {item_id:[{url,file}]};已完整跳过子页,缺文件离线补下。
    """
    if category not in CATEGORIES:
        raise ValueError(f"category 需为 {list(CATEGORIES)}, 收到: {category!r}")
    return asyncio.run(_fetch_category_impl(category, pages, headless, profile_dir, login_state,
                                            assets_root=assets_root, with_images=with_images,
                                            skip_complete_images=skip_complete_images))


def crawl_all(categories: List[str], pages: int = 2, headless: bool = False,
              assets_root: Path = DEFAULT_ASSETS,
              with_images: bool = False) -> dict:
    """依次抓取多个分类,返回 {category: AuctionCrawlResult}。"""
    out = {}
    for c in categories:
        out[c] = fetch_listings(c, pages=pages, headless=headless,
                                assets_root=assets_root, with_images=with_images)
    return out


def download_images(detail: AuctionDetail, listing_id: str, assets_root: Path,
                    timeout: int = 30) -> List[dict]:
    """下载子页图片到 assets/{listing_id}/imgs/,返回 [{url, file}] 结构。

    file: 本地文件名;下载失败为 None。已存在文件跳过(断点续跑),单张失败重试 3 次(退避 1/2/4s)后置 None。
    按 3~5 张一批并发下载(最后不足一批也并发下完)。
    同时把 detail.image_files 对齐填充(与 detail.images 一一对应)。
    """
    target_dir = assets_root / str(listing_id) / "imgs"
    target_dir.mkdir(parents=True, exist_ok=True)
    pending: List[tuple] = []  # (dest, url, idx)
    for idx, img_url in enumerate(detail.images, start=1):
        pending.append((target_dir / f"{idx:02d}.jpg", img_url, idx))
    done: dict = {}  # idx -> {"url", "file"}
    for dest, img_url, idx in pending:
        if dest.exists():
            done[idx] = {"url": img_url, "file": dest.name}
    todo = [p for p in pending if p[2] not in done]
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


def _save_listing(listing: AuctionListing, detail: AuctionDetail, assets_root: Path) -> List[dict]:
    """逐条落盘: 下载图片到 assets_root/{item_id}/imgs/,返回 [{url,file}] 结构。

    图片失败照常保存 meta.json(断点可续);raw 只保留审计文本(阿里无原始行,置 {}).
    """
    target = assets_root / listing.item_id
    target.mkdir(parents=True, exist_ok=True)
    structured = download_images(detail, listing.item_id, assets_root)
    meta = target / "meta.json"
    meta.write_text(
        json.dumps({"listing": listing.to_dict(), "detail": detail.to_dict()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return structured


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
    parser = argparse.ArgumentParser(description="阿里资产(淘宝司法拍卖)列表爬虫(即将开始)")
    parser.add_argument("--category", type=str, nargs="+",
                        default=["住宅"], choices=list(CATEGORIES),
                        help="一个或多个分类,默认 住宅")
    parser.add_argument("--pages", type=int, default=2,
                        help="每个分类抓取的页数(默认 2,0=全部页)")
    parser.add_argument("--headless", action="store_true", default=False,
                        help="无头模式(默认关闭=有头,便于首次登录观察)")
    parser.add_argument("--profile", type=str, default=str(PROFILE_DIR), help="浏览器 profile 目录")
    parser.add_argument("--login-state", type=str, default=str(LOGIN_STATE), help="登录态保存路径")
    parser.add_argument("--download", action="store_true",
                        help="每页抓完立即打开子页采图并下载到 assets/ali/{item_id}/imgs/,元数据存 meta.json")
    parser.add_argument("--assets-root", type=str, default=str(PROJECT_ROOT / "assets" / "ali"),
                        help="下载根目录(配合 --download,默认 assets/ali)")
    parser.add_argument("--db", action="store_true",
                        help="结果 upsert 进 PostgreSQL listings 表(见 .env DATABASE_URL;不可用时自动跳过)")
    parser.add_argument("--skip-complete", action="store_true",
                        help="断点续传(以 DB 为准): 已采完图的子页跳过,缺的文件离线补下,不再开浏览器")
    args = parser.parse_args()

    results = {}
    root = Path(args.assets_root)
    skip_complete = None
    if args.skip_complete and args.download:
        from src.db import get_source_images  # 懒加载

        skip_complete = get_source_images("ali")
        print(f"  断点续传: DB 已采图 {len(skip_complete)} 条可跳过", flush=True)
    for c in args.category:
        results[c] = fetch_listings(c, pages=args.pages, headless=args.headless,
                                    profile_dir=Path(args.profile),
                                    login_state=Path(args.login_state),
                                    assets_root=root,
                                    with_images=args.download,
                                    skip_complete_images=skip_complete)

    for c, r in results.items():
        print(f"\n== [{c}] 声明页数 {r.total}, 解析 {len(r.listings)} 条 ==", flush=True)
        if args.db:
            from src.db import upsert_listing  # 懒加载: DB 不可用时不影响采集

            n_ok = n_fail = 0
            for l in r.listings:
                detail = next((d for d in r.details if d.item_id == l.item_id), None)
                # 结构化图片 [{url,file}]: 已下载的用 detail.image_files,否则回退 DB 已知清单
                known = (skip_complete or {}).get(l.item_id) or []
                images = []
                if detail and detail.image_files:
                    images = [{"url": u, "file": f}
                              for u, f in zip(detail.images, detail.image_files)]
                elif known:
                    images = known
                data = {
                    "images": images,
                    "raw": {k: v for k, v in (l.raw or {}).items() if k not in ("href", "title")},
                }
                row = l.to_dict()
                row.pop("raw", None)
                row["data"] = data
                if upsert_listing(row):
                    n_ok += 1
                else:
                    n_fail += 1
            print(f"  -- 入库 {n_ok} 成功,{n_fail} 失败(DB 不可用会跳过,不影响采集)", flush=True)
        for l in r.listings[:50]:
            print(f"  [{l.item_id}] {l.title} | 起拍 {l.start_price} | 参考 {l.ref_price_type} {l.ref_price} | 图 {len(next((d.images for d in r.details if d.item_id == l.item_id), []))} 张")
        if r.errors:
            print(f"  -- {c} 错误 {len(r.errors)} 条:")
            for e in r.errors[:10]:
                print("   ", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())