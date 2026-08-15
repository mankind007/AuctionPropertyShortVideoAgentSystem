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
import json
import random
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional

from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.schemas.listing import AuctionCrawlResult, AuctionDetail, AuctionListing

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
# 详情页主图轮播(ul.pm-thumb 内 img;需加 https:// 前缀 + _80x80→_960x960)
XP_IMG = "xpath=//ul[contains(concat(' ',@class,' '),' pm-thumb')]//img"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 反检测注入(同步执行,页面任何脚本读取前已生效;淘宝 x5sec 风控更严格)
# 注意: 必须用 IIFE 立即执行,`add_init_script` 不会调用裸 `() => {}` 函数表达式。
STEALTH_SCRIPT = """
(() => {
  try {
    Object.defineProperty(navigator, 'webdriver', {
      get: () => false, configurable: true, enumerable: true,
    });
    Object.defineProperty(navigator, 'plugins', {
      get: () => {
        const make = (name) => ({
          name, filename: 'internal-' + name + '.dll',
          description: 'Portable Document Format', length: 1,
          item: (i) => make(name), namedItem: () => make(name), refresh: () => {},
        });
        return [make('Chrome PDF Plugin'), make('Chrome PDF Viewer')];
      }, configurable: true, enumerable: true,
    });
    Object.defineProperty(navigator, 'mimeTypes', {
      get: () => {
        const mt = (type, desc, suffixes, plugin) => ({
          type, description: desc, suffixes, enabledPlugin: plugin,
        });
        return [mt('application/pdf', 'Portable Document Format', 'pdf', {})];
      }, configurable: true, enumerable: true,
    });
    window.chrome = { runtime: {}, app: {}, loadTimes: function(){}, csi: function(){}, symbolicNames: function(){} };
    Object.defineProperty(navigator, 'languages', {
      get: () => ['zh-CN', 'zh', 'en-US', 'en', 'zh-TW'], configurable: true, enumerable: true,
    });
    Object.defineProperty(navigator, 'hardwareConcurrency', {
      get: () => 8, configurable: true, enumerable: true,
    });
    Object.defineProperty(navigator, 'deviceMemory', {
      get: () => 8, configurable: true, enumerable: true,
    });
    Object.defineProperty(navigator, 'maxTouchPoints', {
      get: () => 0, configurable: true, enumerable: true,
    });
    Object.defineProperty(navigator, 'vendor', {
      get: () => 'Google Inc.', configurable: true, enumerable: true,
    });
    const uaData = {
      brands: [
        { brand: 'Chromium', version: '120' },
        { brand: 'Google Chrome', version: '120' },
        { brand: 'Not?A_Brand', version: '24' },
      ],
      mobile: false, platform: 'Windows',
    };
    try {
      Object.defineProperty(navigator, 'userAgentData', {
        get: () => uaData, configurable: true, enumerable: true,
      });
    } catch (e) {}
    if (window.Permissions && window.Permissions.prototype) {
      const origQuery = window.Permissions.prototype.query;
      window.Permissions.prototype.query = function(query) {
        if (query && query.name === 'notifications') {
          return Promise.resolve({ state: 'denied' });
        }
        return origQuery.call(this, query);
      };
    }
  } catch (e) {}
})();
"""


# 反爬注意: 必须配合 launch 参数一起防检测
LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-infobars",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-dev-shm-usage",
    "--window-size=1366,900",
]

# ---------------------------------------------------------------------------
# 纯函数(可测)
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """当前本地时间 ISO 格式(不含微秒),作为采集时间戳。"""
    import datetime

    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _to_int_price(text: str) -> Optional[float]:
    """把价格文本转成元。容忍开头的 ￥/¥、千分位逗号与任意中文单位组合(百/千/万/十万/百万/千万/亿/十亿)。"""
    if not text:
        return None
    t = text.strip().lstrip("￥¥").strip()
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
    """从文本中提取形如 '开始时间:2026-8-13 10:00:00' 的时间串。"""
    if not text:
        return None
    m = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s*\d{1,2}:\d{2}(?::\d{2})?)", text)
    return m.group(1) if m else None


def _item_url(fragment: str) -> str:
    """列表项链接片段补全为完整 URL。"""
    if not fragment:
        return ""
    if fragment.startswith("http"):
        return fragment
    return "https:" + fragment


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


def _parse_listing(node) -> AuctionListing:
    """从单个 li 节点解析出房源(同步;仅供契约测试喂假节点)。

    真实抓取走 `_fetch_category_impl` 里的异步路径,此函数保证与异步版同结构。
    注: 图片在详情页采集,列表页只解析元数据。
    """
    title_el = node.locator(XP_TITLE).first
    title = title_el.inner_text().strip() if title_el.count() else ""

    href_el = node.locator(XP_ITEM_HREF).first
    href = href_el.get_attribute("href") if href_el.count() else ""
    url = _item_url(href)
    item_id = _extract_item_id(url)

    start_price = 0.0
    sp_el = node.locator(XP_START_PRICE).first
    if sp_el.count():
        start_price = _to_int_price(sp_el.inner_text()) or 0.0

    ref_price = None
    ref_price_type = ""
    ref_el = node.locator(XP_REF_PRICE).first
    if ref_el.count():
        v = _to_int_price(ref_el.inner_text())
        if v is not None:
            ref_price = v
            ref_price_type = "参考价"

    return AuctionListing(
        source="ali",
        title=title,
        url=url,
        item_id=item_id,
        start_price=start_price,
        ref_price=ref_price,
        ref_price_type=ref_price_type,
        start_time=None,
        crawled_at=_now_iso(),
        status="即将开始",
        raw={"href": href or "", "title": title},
    )


async def _wait_human_for_challenge(page, back_url: str, timeout_s: int = 300,
                                    label: str = "") -> bool:
    """检测详情页/子页是否触发滑块/风控,等待人工处理(最多 timeout_s 秒)。

    处理完成后页面会自动跳回 back_url;提前完成则立即返回,无需等满。
    返回 True 表示最终已离开验证页(可继续)。
    """
    if "punish" not in page.url and "x5sec" not in page.url \
            and "login.taobao.com" not in page.url:
        return True
    waited = 0

    async def _still_blocked():
        u = page.url
        return "punish" in u or "x5sec" in u or "login.taobao.com" in u

    while waited < timeout_s:
        if not await _still_blocked():
            print(f"  {label}验证已人工完成,自动继续…", flush=True)
            return True
        print(f"  {label}检测到验证滑块/风控 —— 请在弹出窗口完成验证(最长等待 {timeout_s}s)…",
              flush=True)
        await page.wait_for_timeout(5000)

        if not await _still_blocked():
            continue
        # 5 秒后仍被拦,且 URL 含 login: 重新 goto 回目标页(登录后可能停留在登录页)
        if "login.taobao.com" in page.url:
            try:
                await page.goto(back_url, timeout=45000)
                await page.wait_for_timeout(2000)
            except Exception:  # noqa: BLE001
                pass
        waited += 5
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
        await page.goto(url, timeout=60000, wait_until="domcontentloaded")
        await page.wait_for_timeout(2500)
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
                               with_images: bool = False) -> AuctionCrawlResult:
    """抓取单个分类列表页房源(内部 async 实现)。with_images: 是否打开详情页采集图片。"""
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
        await page.goto(base_url, timeout=45000)
        await page.wait_for_timeout(2500)

        # 鉴权等待: 登录页(login.taobao.com)或风控滑块(punish)都需人工处理
        # 滑块/登录解决后页面会自动跳回列表;最多等待 5 分钟
        item_count = await page.locator(XP_ITEM).count()
        waited = 0
        MAX_WAIT_S = 300
        while item_count == 0 and waited < MAX_WAIT_S:
            u = page.url
            if "punish" in u or "x5sec" in u:
                print("  检测到风控滑块(punish) —— 请在弹出的浏览器窗口里**拖动滑块**完成验证,完成后自动继续…",
                      flush=True)
            elif "login.taobao.com" in u:
                print("  检测到登录页 —— 请在弹窗中完成登录(扫码/输密码),完成后我将自动继续…", flush=True)
            else:
                print(f"  列表加载中(条目 {item_count})… {u[:80]}", flush=True)
            await page.wait_for_timeout(5000)
            # 若刚解决滑块/登录,页面会跳回真实列表 URL;重新 goto 保证拿到列表
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
                await page.goto(f"{base_url}&page={page_num}", timeout=45000)
                await page.wait_for_timeout(2500)
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
                    url = _item_url(href)
                    item_id = _extract_item_id(url)

                    sp = 0.0
                    sp_el = item.locator(XP_START_PRICE).first
                    if await sp_el.count():
                        sp = _to_int_price(await sp_el.inner_text()) or 0.0

                    ref_price = None
                    ref_type = ""
                    ref_el = item.locator(XP_REF_PRICE).first
                    if await ref_el.count():
                        v = _to_int_price(await ref_el.inner_text())
                        if v is not None:
                            ref_price = v
                            ref_type = "参考价"

                    listing = AuctionListing(
                        source="ali",
                        title=title,
                        url=url,
                        item_id=item_id,
                        start_price=sp,
                        ref_price=ref_price,
                        ref_price_type=ref_type,
                        start_time=None,
                        crawled_at=_now_iso(),
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
                    try:
                        d = await _fetch_detail_images(listing.url, browser)
                        detail.images = d.images
                        saved = _save_listing(listing, d, assets_root)
                        print(f"  [{page_num}.{j}] {listing.item_id} 图片 {len(d.images)} 张,"
                              f" 已存 {saved}", flush=True)
                    except Exception as e:  # noqa: BLE001
                        result.errors.append(f"detail {listing.url}: {e}")
        await browser.close()
    return result


def fetch_listings(category: str, pages: int = 2, headless: bool = False,
                   profile_dir: Path = PROFILE_DIR,
                   login_state: Path = LOGIN_STATE,
                   assets_root: Path = DEFAULT_ASSETS,
                   with_images: bool = False) -> AuctionCrawlResult:
    """抓取阿里资产单个分类"即将开始"房源。

    category: 住宅/商业/工业/其他
    pages: 抓取页数,默认 2(至少 MIN_PAGES);0=全部页。
    headless: 默认 False(有头),首次必须;遇到滑块需人工拖动验证后才可复用。
    assets_root: 图片下载 + meta 落盘根目录(默认 assets/ali)。
    with_images: 为 True 时逐个打开子页采集图片(会较慢)。
    """
    if category not in CATEGORIES:
        raise ValueError(f"category 需为 {list(CATEGORIES)}, 收到: {category!r}")
    return asyncio.run(_fetch_category_impl(category, pages, headless, profile_dir, login_state,
                                            assets_root=assets_root, with_images=with_images))


def crawl_all(categories: List[str], pages: int = 2, headless: bool = False,
              assets_root: Path = DEFAULT_ASSETS,
              with_images: bool = False) -> dict:
    """依次抓取多个分类,返回 {category: AuctionCrawlResult}。"""
    out = {}
    for c in categories:
        out[c] = fetch_listings(c, pages=pages, headless=headless,
                                assets_root=assets_root, with_images=with_images)
    return out


def _save_listing(listing: AuctionListing, detail: AuctionDetail, assets_root: Path) -> int:
    """逐条落盘: 下载图片到 assets_root/{item_id}/imgs/01.jpg…,并把元数据写到 meta.json。

    返回成功下载的图片数。即使图片失败,meta 也照常保存(断点可续)。
    """
    target = assets_root / listing.item_id
    target.mkdir(parents=True, exist_ok=True)
    n = download_images(detail, listing.item_id, assets_root)
    meta = target / "meta.json"
    meta.write_text(
        json.dumps({"listing": listing.to_dict(), "detail": detail.to_dict()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return n


def _download_chunk(tasks, timeout: int) -> List[str]:
    """并发下载一批图片,返回成功的本地路径。

    tasks: [(dest_path, img_url), ...]。单张失败跳过不中断(容错)。
    """
    saved = []

    def _one(task):
        dest, img_url = task
        req = urllib.request.Request(img_url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as f:
                f.write(resp.read())
            return str(dest)
        except Exception:  # noqa: BLE001
            return None

    with ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        for r in pool.map(_one, tasks):
            if r:
                saved.append(r)
    return saved


def download_images(detail: AuctionDetail, listing_id: str, assets_root: Path,
                    timeout: int = 30) -> List[str]:
    """下载封面图到 assets/{listing_id}/imgs/,返回本地路径列表。

    每个子页的所有图片都必须下载,但不是一张张下: 先随机取 x∈{3,4,5},
    按 x 张一批并发下载;最后不足 x 张的一批也全部并发下完。
    已存在的文件跳过(断点续跑),失败图片跳过不中断。
    """
    saved = []
    target_dir = assets_root / str(listing_id) / "imgs"
    target_dir.mkdir(parents=True, exist_ok=True)
    pending = []
    for idx, img_url in enumerate(detail.images, start=1):
        dest = target_dir / f"{idx:02d}.jpg"
        if dest.exists():
            saved.append(str(dest))
            continue
        pending.append((dest, img_url))
    x = random.randint(3, 5)
    for i in range(0, len(pending), x):
        saved.extend(_download_chunk(pending[i:i + x], timeout))
    return saved


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
    args = parser.parse_args()

    results = {}
    root = Path(args.assets_root)
    for c in args.category:
        results[c] = fetch_listings(c, pages=args.pages, headless=args.headless,
                                    profile_dir=Path(args.profile),
                                    login_state=Path(args.login_state),
                                    assets_root=root,
                                    with_images=args.download)

    for c, r in results.items():
        print(f"\n== [{c}] 声明页数 {r.total}, 解析 {len(r.listings)} 条 ==", flush=True)
        for l in r.listings[:50]:
            print(f"  [{l.item_id}] {l.title} | 起拍 {l.start_price} | 参考 {l.ref_price_type} {l.ref_price} | 图 {len(next((d.images for d in r.details if d.item_id == l.item_id), []))} 张")
        if r.errors:
            print(f"  -- {c} 错误 {len(r.errors)} 条:")
            for e in r.errors[:10]:
                print("   ", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())