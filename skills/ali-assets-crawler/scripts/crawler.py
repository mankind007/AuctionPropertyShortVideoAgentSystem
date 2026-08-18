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

from app.schemas.listing import AuctionCrawlResult, AuctionDetail, AuctionListing
from utils.browser import LAUNCH_ARGS, STEALTH_SCRIPT, UA
from utils.description import extract_auction_description, extract_property_info
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


def _is_icon_image(url: str) -> bool:
    """剔除混入轮播的短视频播放图标(非房源图)。

    特征: imgextra CDN 路径、`tps-72-72.png` 这类缩略占位/图标 URL。
    """
    if not url:
        return True
    return ("imgextra" in url or "-tps-" in url or "tps-" in url)


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


def _is_placeholder_description(desc: str) -> bool:
    """描述是否为占位文案(公告详情加载中/加载中),判缺与 merge 自愈共用。"""
    return bool(desc) and ("公告详情" in desc or "加载中" in desc)


def merge_db_data(new_title: str, rec: Optional[dict],
                  detail_images: List[dict], detail: Optional[AuctionDetail]) -> dict:
    """写库 data 组装: 标题变化=新数据清空重建,否则以旧 data 为底 merge。

    - rec: DB 旧记录 {title, images, poi, data}(无则 None)
    - detail_images: 本次已下载的 [{url,file}] 结构(为空则回退旧清单)
    - detail: 本次抓取结果(可能为空壳,仅用非空字段覆盖)
    返回最终 data dict(含 images/raw 与可用的 description/property_info/poi)。
    """
    rec_data = dict(rec.get("data") or {}) if rec else {}
    title_changed = rec is not None and (rec.get("title") or "") != (new_title or "")
    data = {} if (title_changed or not rec_data) else rec_data

    images = detail_images
    if not images and rec:
        images = rec.get("images") or []
    data["images"] = images

    if detail and detail.description:
        data["description"] = detail.description
    elif rec and _is_placeholder_description(str(data.get("description", ""))):
        # 旧描述是占位文案(公告详情加载中)且本次未抓到真描述 → 主动清除,避免误导下游
        data.pop("description", None)
    if detail and detail.property_info:
        data["property_info"] = detail.property_info
    if getattr(detail, "_poi_captured", False):
        data["poi"] = {
            "transportation": detail.transportation,
            "education": detail.education,
            "shopping": detail.shopping,
            "medical": detail.medical,
            "parks": detail.parks,
        }
    elif rec and rec.get("poi") is not None:
        data["poi"] = rec["poi"]
    if title_changed:
        data.pop("_empty", None)
    return data


async def _dom_blocked(page) -> bool:
    """滑块 DOM 是否在页面上(#nc_1_* = 阿里滑块)。"""
    try:
        return await page.locator("#nc_1__scale_text, #nc_1_nz1, #nc_1_n1z").count() > 0
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
        handle = page.locator("#nc_1_nz1, #nc_1_n1z")
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
        # 按下前随机停顿 1-2s(过快会被行为风控判定为机器人)
        await page.wait_for_timeout(random.randint(1000, 2000))
        await page.mouse.down()
        # 缓动曲线: 前快后慢 + 随机抖动/停顿,模拟人手;整体拖动耗时尽量拉长(>=1.5s)
        n_steps = random.randint(30, 45)
        for i in range(1, n_steps + 1):
            progress = i / n_steps
            eased = 1 - (1 - progress) ** 2
            cur_x = start_x + distance * eased + random.uniform(-1.2, 1.2)
            await page.mouse.move(cur_x, y + random.uniform(-1.0, 1.0), steps=1)
            # 拖动中随机停顿(每步小停顿 + 每 5-9 步大停顿),拖满过程最少 ~1.5s
            await page.wait_for_timeout(random.randint(20, 60))
            if i % random.randint(5, 9) == 0:
                await page.wait_for_timeout(random.randint(400, 900))
        await page.mouse.move(start_x + distance + random.uniform(0, 2), y, steps=2)
        # 释放前随机停顿 1-2s,模拟对准后的犹豫
        await page.wait_for_timeout(random.randint(1000, 2000))
        await page.mouse.up()
        # 释放后留出服务端校验时间(1.8-3s)
        await page.wait_for_timeout(random.randint(1800, 3000))
        if not await _still_blocked(page):
            return True
    return False


async def _wait_human_for_challenge(page, back_url: str, timeout_s: int = 300,
                                    label: str = "") -> bool:
    """检测列表页/详情页是否触发登录/滑块/风控。

    判定方式(URL + DOM 双通道):
    - URL: punish / x5sec / login.taobao.com
    - DOM: #nc_1__scale_text(滑轨) / #nc_1_nz1、#nc_1_n1z(滑块把手)
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


async def _get_active_main_tag(frame) -> str:
    """获取当前激活的主标签文本(带 activePoiName-- 类的 <p>)。"""
    try:
        els = frame.locator("p[class*='activePoiName--']")
        if await els.count():
            return (await els.first.inner_text()).strip()
    except Exception:
        pass
    return ""


async def _get_active_sub_tag(frame) -> str:
    """获取当前激活的二级标签文本(带 selectedChildPoiName-- 类的 <p>)。"""
    try:
        els = frame.locator("p[class*='selectedChildPoiName--']")
        if await els.count():
            return (await els.first.inner_text()).strip()
    except Exception:
        pass
    return ""


async def _fetch_surrounding_info(page, browser) -> dict:
    """抓取详情页的周围情况(标的物位置下方的高德地图iframe数据)。"""
    import random
    
    poi = {
        "transportation": {},
        "education": {},
        "shopping": {},
        "medical": {},
        "parks": []
    }
    
    # 首次加载：滚动到标的物位置 + 分段随机滚动触发iframe懒加载
    try:
        address_el = page.locator("xpath=//div[contains(@class,'item-address')]").first
        if await address_el.count():
            await address_el.scroll_into_view_if_needed()
            await page.wait_for_timeout(1000)
    except Exception:
        pass
    
    for _ in range(random.randint(3, 5)):
        await page.mouse.wheel(0, random.randint(300, 700))
        await page.wait_for_timeout(random.randint(400, 800))
    await page.wait_for_timeout(2000)
    
    # 等待gaode iframe出现(最多300秒)
    frame = None
    for _ in range(300):
        for f in page.frames:
            if "gaode-map-pc" in f.url:
                frame = f
                break
        if frame:
            break
        await page.wait_for_timeout(1000)
    
    if not frame:
        print("  [周围情况] 未找到高德iframe", flush=True)
        return poi
    
    # frame 级隐式等待(最大10秒, frame 继承 page 默认超时)
    page.set_default_timeout(10000)
    await frame.wait_for_timeout(random.randint(500, 1500))
    
    # 定义标签配置: (主标签, 二级标签列表, 英文key)
    tag_configs = [
        ("交通", ["地铁", "公交"], "transportation"),
        ("教育", ["幼儿园", "小学", "中学"], "education"),
        ("购物", ["购物中心", "超市", "农贸市场"], "shopping"),
        ("医疗", ["综合医院", "卫生服务站", "其他医院", "药店"], "medical"),
        ("公园", [], "parks"),
    ]
    
    for main_tag, sub_tags, eng_key in tag_configs:
        try:
            main_tab = frame.locator("div.h-48px p", has_text=main_tag).first
            if not await main_tab.count():
                continue
            # 点击主标签并验证切换(最多3次)
            switched = False
            for attempt in range(3):
                await main_tab.click(force=True)
                await frame.wait_for_timeout(random.randint(1500, 2500))
                if await _get_active_main_tag(frame) == main_tag:
                    switched = True
                    break
                print(f"  [{main_tag}] 主标签切换未生效, 再等3s重试(第{attempt+1}次)", flush=True)
                await frame.wait_for_timeout(3000)
            if not switched:
                print(f"  [{main_tag}] 主标签最终未切换成功, 跳过", flush=True)
                continue
            print(f"  [{main_tag}] 主标签已激活", flush=True)
            
            if main_tag == "公园":
                items = await _fetch_poi_items(frame)
                if not items:
                    # 情况C: 切换成功但无数据, 再等2s确认
                    await frame.wait_for_timeout(2000)
                    items = await _fetch_poi_items(frame)
                print(f"  [{main_tag}] 抓取到 {len(items)} 条", flush=True)
                if items:
                    poi[eng_key] = items
            else:
                tag_data = {}
                for sub_tag in sub_tags:
                    try:
                        sub_tab = frame.locator("div.h-44px p", has_text=sub_tag).first
                        if not await sub_tab.count():
                            continue
                        # 点击二级标签并验证切换(最多3次)
                        switched = False
                        for attempt in range(3):
                            await sub_tab.click(force=True)
                            await frame.wait_for_timeout(random.randint(1500, 2500))
                            if await _get_active_sub_tag(frame) == sub_tag:
                                switched = True
                                break
                            print(f"  [{main_tag}>{sub_tag}] 二级标签切换未生效, 再等3s重试(第{attempt+1}次)", flush=True)
                            await frame.wait_for_timeout(3000)
                        if not switched:
                            print(f"  [{main_tag}>{sub_tag}] 二级标签最终未切换成功, 跳过", flush=True)
                            continue
                        items = await _fetch_poi_items(frame)
                        if not items:
                            # 情况C: 切换成功但无数据, 再等2s确认
                            await frame.wait_for_timeout(2000)
                            items = await _fetch_poi_items(frame)
                        print(f"  [{main_tag}>{sub_tag}] 抓取到 {len(items)} 条", flush=True)
                        if items:
                            tag_data[sub_tag] = items
                    except Exception as e:
                        print(f"  [{main_tag}>{sub_tag}] 错误: {e}", flush=True)
                if tag_data:
                    poi[eng_key] = tag_data
        except Exception as e:
            print(f"  [{main_tag}] 错误: {e}", flush=True)
    
    return poi


async def _fetch_poi_items(frame) -> list:
    """从poiSearchInfo容器抓取条目列表。"""
    items = []
    try:
        # 检查poiSearchInfo元素是否存在
        poi_count = await frame.locator("div[class*='poiSearchInfo']").count()
        
        # 使用JavaScript抓取所有条目
        raw_items = await frame.eval_on_selector_all(
            "div[class*='poiSearchInfo'] > div",
            """els => els.map(e => {
                const nameDescDiv = e.querySelector('div');
                const distP = e.querySelector(':scope > p');
                const ps = nameDescDiv ? nameDescDiv.querySelectorAll('p') : [];
                const name = ps[0] ? ps[0].innerText.trim() : '';
                const desc = ps[1] ? ps[1].innerText.trim() : '';
                const distance = distP ? distP.innerText.trim() : '';
                return {name, desc, distance};
            }).filter(e => e.name)"""
        )
        items = raw_items
    except Exception as e:
        print(f"  _fetch_poi_items error: {e}", flush=True)
    return items


async def _open_detail_page(url: str, browser, page=None):
    """打开子页并处理登录/滑块,直到主图可用;返回 page(由调用方负责关闭)。

    提供独立 page 上下文给 _fetch_images / _fetch_description / _fetch_surrounding_info
    复用,避免各采集接口各自开页重复触发鉴权。
    默认新建页;传 page 时复用该页不新开标签(供并行补填场景,避免逐条开标签)。
    """
    if page is None:
        page = await browser.new_page()
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
            break
        # 已在目标页但主图还没加载/被拦(可能刚解决验证页面正在回到详情),再短暂等待重试
        if "punish" in page.url or "x5sec" in page.url or "login.taobao.com" in page.url:
            continue
        await page.wait_for_timeout(2000)
    return page


async def _fetch_images(page) -> List[str]:
    """抓取详情页主图轮播链接(独立接口)。

    过滤播放图标(imgextra/tps- 缩略占位)并按 URL 去重(轮播可能重复引用同一张图)。
    """
    srcs = await page.eval_on_selector_all(
        XP_IMG,
        "els => els.map(e => e.getAttribute('src') || e.getAttribute('data-src')).filter(Boolean)",
    )
    urls = [s for s in srcs if not _is_icon_image(s)]
    seen, out = set(), []
    for s in urls:
        u = _fix_img_src(s)
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out


async def _fetch_description(page) -> str:
    """抓取标的物描述(独立接口);无描述或仍是加载占位文案时返回空串。

    公告内容为动态加载,J_NoticeDetail 先显示「公告详情加载…」,轮询等待真实内容;
    按 docs/初步信息 + 需求.txt 分段提取(见 utils.description)。
    """
    desc_el = page.locator("xpath=//div[@id='J_NoticeDetail']")
    if not await desc_el.count():
        return ""
    text = (await desc_el.first.inner_text()).strip()
    for _ in range(10):
        if "公告详情" in text or "加载" in text:
            await page.wait_for_timeout(1500)
            text = (await desc_el.first.inner_text()).strip()
        else:
            break
    if not text or len(text) < 6 or "公告详情" in text or "加载" in text:
        return ""
    return extract_auction_description(text)


async def _fetch_property_info(page) -> dict:
    """抓取「标的物属性」区块并按 `键：值` 解析为结构化 dict; 无该区块返回 {}。

    该区块标题为无class的内联样式div(文本=标的物属性),属性键值在其后的文本里;
    用 JS 从标题节点向上找第一个文本明显变长的祖先容器再交 `extract_property_info` 截取。
    """
    label = page.locator("xpath=//div[normalize-space()='标的物属性']").first
    if not await label.count():
        return {}
    raw = await label.evaluate(
        """(el) => {
            let node = el;
            for (let i = 0; i < 10 && node; i++) {
                const txt = (node.innerText || '').trim();
                if (txt.length > 40) return txt;
                node = node.parentElement;
            }
            return '';
        }"""
    )
    return extract_property_info(raw)


async def _fetch_property_info_from_intro(page) -> dict:
    """兜底: 从「标的物介绍」tab 内容表解析属性(老模板无「标的物属性」区块时)。

    老模板(sf_item): 标的物介绍 tab 是 `div.addition-desc.J_Content`(动态渲染),
    内含结构化 <table>; 每行 `{键, 值}` 两格, 分组行带 rowspan 组名时为
    `{组名, 子键, 值}` 三格(子键+值算一对)。返回 {键: 值} dict, 无表返回 {}。
    """
    return await page.evaluate("""() => {
        const c = document.querySelector('div.addition-desc.J_Content, #J_ItemDetailContent');
        if (!c) return {};
        const tbl = c.querySelector('table');
        if (!tbl) return {};
        const out = {};
        for (const tr of tbl.querySelectorAll('tr')) {
            const tds = [...tr.querySelectorAll(':scope > td, :scope > th')];
            if (tds.length < 2) continue;
            // 三格分组行忽略 rowspan 组名列, 取末尾两格为键/值
            const k = (tds[tds.length - 2].innerText || '').trim();
            const v = (tds[tds.length - 1].innerText || '').trim();
            if (k && v) out[k] = v;
        }
        return out;
    }""")


async def _fetch_location(page) -> str:
    """抓取标的物具体位置(独立接口, docs: //div[@class='detail-common-text item-address']);无则空串。"""
    loc_el = page.locator("xpath=//div[contains(@class,'item-address')]").first
    if await loc_el.count():
        return (await loc_el.inner_text()).strip()
    return ""


async def _fetch_detail(url: str, browser) -> AuctionDetail:
    """打开子页并收集详情: 主图 + 标的物描述 + 周围情况(组合多个独立接口)。"""
    item_id = _extract_item_id(url)
    detail = AuctionDetail(source="ali", item_id=item_id)
    page = await _open_detail_page(url, browser)
    try:
        detail.images = await _fetch_images(page)
        # 标的物属性优先级 > 标的物描述: susong模板无拍卖标的描述但有属性区块,
        # 属性已抓到就不再抓描述(描述恒为占位/空,白占 1.5s×10 轮询)
        # 无「标的物属性」区块时兜底解析「标的物介绍」tab 内容表(老模板)
        detail.property_info = await _fetch_property_info(page)
        if not detail.property_info:
            detail.property_info = await _fetch_property_info_from_intro(page)
        if not detail.property_info:
            detail.description = await _fetch_description(page)
        poi = await _fetch_surrounding_info(page, browser)
        detail.transportation = poi.get("transportation", {})
        detail.education = poi.get("education", {})
        detail.shopping = poi.get("shopping", {})
        detail.medical = poi.get("medical", {})
        detail.parks = poi.get("parks", [])
    finally:
        await page.close()
    return detail


async def _fetch_category_impl(category: str, pages: int, headless: bool,
                               profile_dir: Path, login_state: Path,
                               assets_root: Path = DEFAULT_ASSETS,
                               with_images: bool = False,
                               skip_complete: Optional[dict] = None) -> AuctionCrawlResult:
    """抓取单个分类列表页房源(内部 async 实现)。with_images: 是否打开详情页采集图片。

    skip_complete: DB 断点续传清单 {item_id: {"images":[{url,file}], "poi": {…}|None}}。
      - images 齐 + poi 在库 → 整页跳过(不开浏览器)
      - images 齐但 poi 缺 → 开浏览器补周围+描述(图不重复下载)
      - poi 在库但图缺 → 用 DB url 离线补图(不开浏览器)
      - 均缺/无记录 → 全量开页抓取
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
                    # 断点续传(以 DB 为准): 标题变化=新数据需重建;标题相同按缺补抓
                    rec = (skip_complete or {}).get(listing.item_id)
                    if rec is not None:
                        title_changed = (rec.get("title") or "") != (listing.title or "")
                        imgs = rec.get("images") or []
                        files_ok = bool(imgs) and all(
                            x.get("file") and (assets_root / listing.item_id / "imgs" / x["file"]).exists()
                            for x in imgs)
                        poi_ok = rec.get("poi") is not None
                        old_data = rec.get("data") or {}
                        # 描述/属性已有视为不缺(占位文案视为缺)
                        desc_ok = bool(old_data.get("description")) and "公告详情" not in str(old_data.get("description"))
                        prop_ok = bool(old_data.get("property_info"))
                        empty_ok = bool(old_data.get("_empty"))
                        if not title_changed and files_ok and poi_ok and desc_ok and prop_ok:
                            print(f"  [{page_num}.{j}] {listing.item_id} 已完整,跳过子页", flush=True)
                            continue
                        if not title_changed and empty_ok:
                            # 标题相同且此前标记过 _empty(确无内容) → 不再开页,仅确保 images/poi 不丢
                            detail.images = [x["url"] for x in imgs] if imgs else []
                            detail._poi_captured = False
                            print(f"  [{page_num}.{j}] {listing.item_id} 已标记空数据,跳过子页", flush=True)
                            continue
                        if title_changed:
                            print(f"  [{page_num}.{j}] {listing.item_id} 标题变化(新数据),重建 data …", flush=True)
                        elif poi_ok and not files_ok:
                            detail.images = [x["url"] for x in imgs]
                            files = download_images(detail, listing.item_id, assets_root)
                            print(f"  [{page_num}.{j}] {listing.item_id} 周围已齐/图缺,离线补图 "
                                  f"{len([f for f in files if f.get('file')])} 张", flush=True)
                            continue
                        else:
                            print(f"  [{page_num}.{j}] {listing.item_id} 缺字段,开浏览器补 …", flush=True)
                    try:
                        d = await _fetch_detail(listing.url, browser)
                        detail.images = d.images
                        detail.description = d.description
                        detail.transportation = d.transportation
                        detail.education = d.education
                        detail.shopping = d.shopping
                        detail.medical = d.medical
                        detail.parks = d.parks
                        detail._poi_captured = True
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
                   skip_complete: Optional[dict] = None) -> AuctionCrawlResult:
    """抓取阿里资产单个分类"即将开始"房源。

    category: 住宅/商业/工业/其他
    pages: 抓取页数,默认 2(至少 MIN_PAGES);0=全部页。
    headless: 默认 False(有头),首次必须;遇到滑块需人工拖动验证后才可复用。
    assets_root: 图片下载 + meta 落盘根目录(默认 assets/ali)。
    with_images: 为 True 时逐个打开子页采集图片(会较慢)。
    skip_complete: DB 断点续传清单 {item_id: {"title","images","poi","data"}}。
      - 标题变化(新数据) → 重建 data 全量抓取
      - 标题相同: 图齐+poi齐+描述齐+属性齐 → 跳过;缺字段 → 开浏览器补抓
      - 标题相同且标过 _empty → 跳过(该页确无内容)
    """
    if category not in CATEGORIES:
        raise ValueError(f"category 需为 {list(CATEGORIES)}, 收到: {category!r}")
    return asyncio.run(_fetch_category_impl(category, pages, headless, profile_dir, login_state,
                                            assets_root=assets_root, with_images=with_images,
                                            skip_complete=skip_complete))


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
        from db import get_source_data  # 懒加载

        src = get_source_data("ali")
        skip_complete = {}
        for k, v in src.items():
            rec_data = v.get("data") or {}
            imgs = rec_data.get("images") or []
            skip_complete[k] = {
                "title": v.get("title"),
                "images": imgs,
                "poi": rec_data.get("poi"),
                "data": rec_data,
            }
        n_poi = sum(1 for v in skip_complete.values() if v["poi"] is not None)
        n_data = sum(1 for v in skip_complete.values() if v["data"])
        print(f"  断点续传: DB 已有 {len(skip_complete)} 条,其中 poi 已齐 {n_poi} 条,含 data 字段 {n_data} 条",
              flush=True)
    for c in args.category:
        results[c] = fetch_listings(c, pages=args.pages, headless=args.headless,
                                    profile_dir=Path(args.profile),
                                    login_state=Path(args.login_state),
                                    assets_root=root,
                                    with_images=args.download,
                                    skip_complete=skip_complete)

    for c, r in results.items():
        print(f"\n== [{c}] 声明页数 {r.total}, 解析 {len(r.listings)} 条 ==", flush=True)
        if args.db:
            from db import upsert_listing  # 懒加载: DB 不可用时不影响采集

            n_ok = n_fail = 0
            for l in r.listings:
                detail = next((d for d in r.details if d.item_id == l.item_id), None)
                rec = (skip_complete or {}).get(l.item_id)
                images = []
                if detail and detail.image_files:
                    images = [{"url": u, "file": f}
                              for u, f in zip(detail.images, detail.image_files)]
                data = merge_db_data(l.title or "", rec, images, detail)
                data["raw"] = {k: v for k, v in (l.raw or {}).items() if k not in ("href", "title")}
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