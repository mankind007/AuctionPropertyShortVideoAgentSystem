"""脚本: 为 DB 中标缺失 description / location(仅阿里) / property_info 的房源一次性补填。

原理: 描述/位置/属性为纯文本,抓取快,不进断点续传;巡检 DB 中 data 缺这些字段的记录,
逐个打开详情页抓取后合并回 data 并 upsert。结果仍保留原 images/raw/poi 等字段。
阿里「标的物属性」优先: 抓到 property_info 就不再抓 description(描述轮询 10×1.5s 白费);
无「标的物属性」区块时兜底解析「标的物介绍」tab 内容表(老模板结构化 <table>)。
公拍: 抓 描述(d-article)+ 标的物介绍调查情况表(property_info,结构化表格拍扁)。
轨道内全空(desc+prop 均无)打 _empty 收敛,location 单独存在不影响该判定。
自愈: 旧 description 是占位文案(公告详情/加载中)且本次未抓到真描述 → 主动删除,避免误导下游。

并行: 两源同时起浏览器;每源只开固定 --workers 个标签页复用(默认 3),不逐条开新标签。
节流: 每个标签页每次开页面前随机等 0.8-2s,每 5 页额外随机等 2-3.5s。

用法:
    python scripts/fill_description_location.py [--source ali|gpai|all] [--limit 100] [--workers 3]
    python scripts/fill_description_location.py --reparse-description [--source ali|gpai|all]
说明: 阿里填 描述+位置(item-address)+标的物属性(property_info);公拍填 描述+标的物介绍(property_info)。
--reparse-description: 存量含真实「拍卖标的:」标记的整篇描述按分段规则重提取(不开浏览器), 无法分段的打印链接。
注: data 列为 PostgreSQL `json` 类型,判断空对象用 `data->>'property_info' = '{}'`(文本比较,勿用 jsonb 转换)。
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

_ALI = PROJECT_ROOT / "skills" / "ali-assets-crawler" / "scripts" / "crawler.py"
_GPAI = PROJECT_ROOT / "skills" / "gpai-crawler" / "scripts" / "crawler.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ALI = _load(_ALI, "ali_crawler")
GPAI = _load(_GPAI, "gpai_crawler")

from db import session_scope, upsert_listing  # noqa: E402


def _missing(source: str, limit: int) -> list:
    """返回待补填 [(item_id, url, data)],倒序最新优先。

    阿里: 描述缺 且 标的物属性(property_info)也缺 → 需要补描述/属性;位置缺仍要补。
    已抓全空打 `_empty` 标记的记录不再反复筛中(wart 收敛)。
    注意: data 为 PostgreSQL `json` 列,判断空对象一律用 `->>` 文本比较。
    """
    from sqlalchemy import text

    desc_needed = ("(data->>'description' IS NULL OR data->>'description' = '' "
                   "OR data->>'description' LIKE '%公告详情%')")
    if source == "ali":
        prop_needed = ("(data->>'property_info' IS NULL OR data->>'property_info' = '' "
                       "OR data->>'property_info' = '{}')")
        # desc 或 prop 任一缺失即筛中: 只补缺失字段,已存在的 desc/prop 不会被覆盖
        cond_missing = (f"(({desc_needed}) OR ({prop_needed}) "
                        "OR (data->'location' IS NULL)) AND "
                        "(data->>'_empty' IS NULL)")
    else:
        prop_needed = ("(data->>'property_info' IS NULL OR data->>'property_info' = '' "
                       "OR data->>'property_info' = '{}')")
        cond_missing = (f"(({desc_needed}) OR ({prop_needed})) AND "
                        "(data->>'_empty' IS NULL)")
    sql = ("SELECT item_id, url, data FROM listings "
           f"WHERE source=:src AND ({cond_missing}) ORDER BY item_id DESC")
    if limit > 0:
        sql += f" LIMIT {limit}"
    out = []
    try:
        with session_scope() as s:
            for item_id, url, data in s.execute(text(sql), {"src": source}):
                out.append((item_id, url, (data or {})))
    except Exception as e:  # noqa: BLE001
        print(f"  ! 查询 DB 失败: {e}", flush=True)
    return out


async def _run_source(source: str, limit: int, headless: bool, workers: int) -> int:
    rows = _missing(source, limit)
    print(f"[{source}] 待补填 {len(rows)} 条,并行标签页 {workers} 个(固定复用,不逐条开)", flush=True)
    if not rows:
        return 0
    from playwright.async_api import async_playwright
    from utils.browser import get_profile, render_stealth_script

    tag = source
    async with async_playwright() as p:
        if source == "ali":
            profile = get_profile()
            browser = await p.chromium.launch_persistent_context(
                str(ALI.PROFILE_DIR), headless=headless, user_agent=profile["ua"],
                viewport={"width": 1366, "height": 900}, locale="zh-CN",
                timezone_id="Asia/Shanghai", args=ALI.LAUNCH_ARGS,
                ignore_default_args=["--enable-automation"],
            )
        else:
            profile = get_profile()
            browser = await p.chromium.launch(headless=True, user_agent=profile["ua"],
                                              args=GPAI.LAUNCH_ARGS,
                                              ignore_default_args=["--enable-automation"])
        pages = [await browser.new_page() for _ in range(workers)]
        if source == "gpai":
            stealth = render_stealth_script(
                profile, clean_cdp=True, patch_platform=True, patch_ua=True, patch_canvas=True)
            for pg in pages:
                await pg.set_extra_http_headers({"Accept-Language": "zh-CN,zh;q=0.9"})
                pg.set_default_timeout(30000)
                await pg.add_init_script(stealth)

        items_q = asyncio.Queue()
        for r in rows:
            await items_q.put(r)

        async def worker(page) -> int:
            n_ok = 0
            opened = 0
            while True:
                try:
                    item = items_q.get_nowait()
                except asyncio.QueueEmpty:
                    return n_ok
                # 同浏览器页面节流: 每次开页面前随眠 0.8-2s; 每 5 页额外等 2-3.5s
                opened += 1
                if opened % 5 == 0:
                    await page.wait_for_timeout(int(random.uniform(2000, 3500)))
                else:
                    await page.wait_for_timeout(int(random.uniform(800, 2000)))
                item_id, url, data = item
                try:
                    if source == "ali":
                        rpage = await ALI._open_detail_page(url, browser, page=page)
                        # 标的物属性优先: 已有属性则不再抓描述(描述轮询 10×1.5s 白费);
                        # DB 中已有 property_info 则跳过抓取(补位置场景),仅打印提示
                        prop_existing = bool((data or {}).get("property_info"))
                        prop = (data or {}).get("property_info") if prop_existing else {}
                        if prop_existing:
                            print(f"  [{tag}] {item_id} 属性已存 {len(prop)} 项,跳过抓取", flush=True)
                        else:
                            prop = await ALI._fetch_property_info(rpage)
                        if not prop:
                            prop = await ALI._fetch_property_info_from_intro(rpage)
                        loc = await ALI._fetch_location(rpage)
                        desc = await ALI._fetch_description(rpage) if not prop else ""
                        if not (desc or prop):
                            # wart 收敛: 属性(标的物属性区块+标的物介绍表兜底)与描述均无,
                            # 页面确无结构化内容可补(可能有附件/位置),打 _empty 不再反复筛中;
                            # location 仍在则照存,仅不再为 desc/prop 反复开浏览器
                            data2 = dict(data)
                            if loc:
                                data2["location"] = loc
                            data2["_empty"] = True
                            upsert_listing({"source": source, "item_id": item_id, "data": data2})
                            print(f"  [{tag}] {item_id} 描述/属性均空,标记 _empty 跳过 | {url}", flush=True)
                            continue
                        data = dict(data)
                        if desc:
                            data["description"] = desc
                        elif ALI._is_placeholder_description(str(data.get("description", ""))):
                            # 旧描述是占位文案且本次未抓到真描述 → 清除,避免误导下游
                            data.pop("description", None)
                        if loc:
                            data["location"] = loc
                        if prop:
                            data["property_info"] = prop
                        data.pop("_empty", None)
                        upsert_listing({"source": source, "item_id": item_id, "data": data})
                        n_ok += 1
                        print(f"  [{tag}] {item_id} 描述 {len(desc)}字 / 位置 {len(loc)}字 / 属性 {len(prop)}项", flush=True)
                    else:
                        await GPAI._open_detail_page(url, page, profile)
                        desc = await GPAI._fetch_description(page)
                        prop = await GPAI._fetch_property_info(page)
                        if not desc and not prop:
                            # gpai 页面确无描述/属性,同样 _empty 标记收敛
                            data2 = dict(data)
                            data2["_empty"] = True
                            upsert_listing({"source": source, "item_id": item_id, "data": data2})
                            print(f"  [{tag}] {item_id} 描述/属性均空,标记 _empty 跳过 | {url}", flush=True)
                            continue
                        data = dict(data)
                        if desc:
                            data["description"] = desc
                        if prop:
                            data["property_info"] = prop
                        data.pop("_empty", None)
                        upsert_listing({"source": source, "item_id": item_id, "data": data})
                        n_ok += 1
                        print(f"  [{tag}] {item_id} 描述 {len(desc)}字 / 属性 {len(prop)}项", flush=True)
                except Exception as e:  # noqa: BLE001
                    print(f"  [{tag}] {item_id} 抓取失败: {e} | {url}", flush=True)
            return n_ok

        results = await asyncio.gather(*(worker(pg) for pg in pages))
        await browser.close()
    return sum(results)


def _reparse(source: str, limit: int) -> int:
    """对已存整篇描述(含真实「拍卖标的:」标记)按分段规则重提取回填; 无法提取的打印链接。"""
    from sqlalchemy import text
    from utils.description import extract_auction_description

    sql = ("SELECT item_id, url, data FROM listings "
           "WHERE source=:src AND data->'description' IS NOT NULL "
           "AND data->>'description' ~ :pat ORDER BY item_id DESC")
    if limit > 0:
        sql += f" LIMIT {limit}"
    n_ok = n_fail = 0
    try:
        with session_scope() as s:
            for item_id, url, data in s.execute(text(sql), {"src": source, "pat": "拍卖标的(物)?[:：]"}):
                data = dict(data or {})
                raw = data.get("description", "")
                try:
                    new = extract_auction_description(raw)
                except Exception as e:  # noqa: BLE001
                    print(f"  [{source}] {item_id} 提取异常: {e} | {url}", flush=True)
                    n_fail += 1
                    continue
                if new != raw:
                    data["description"] = new
                    if upsert_listing({"source": source, "item_id": item_id, "data": data}):
                        n_ok += 1
                else:
                    print(f"  [{source}] {item_id} 标记后文本过短,无法分段 | {url}", flush=True)
                    n_fail += 1
    except Exception as e:  # noqa: BLE001
        print(f"  ! 重提取查询失败: {e}", flush=True)
    print(f"[{source}] 重提取: 更新 {n_ok} 条, 无法处理 {n_fail} 条", flush=True)
    return n_ok


async def _amain(sources: list, limit: int, headless: bool, workers: int) -> int:
    results = await asyncio.gather(
        *(_run_source(s, limit, headless, workers) for s in sources),
        return_exceptions=True,
    )
    total = 0
    for src, r in zip(sources, results):
        if isinstance(r, BaseException):
            print(f"[{src}] 执行失败: {r}", flush=True)
        else:
            total += r
    return total


def _run_reparse(sources: list, limit: int) -> int:
    total = 0
    for src in sources:
        total += _reparse(src, limit)
    print(f"重提取完成,共更新 {total} 条", flush=True)
    return total


def main() -> int:
    parser = argparse.ArgumentParser(description="为 DB 中标缺失 description/location 的记录一次性补填")
    parser.add_argument("--source", default="all", choices=["ali", "gpai", "all"],
                        help="补哪个源(默认 all);阿里填 描述+位置,公拍只填描述")
    parser.add_argument("--limit", type=int, default=0, help="最多补几条(0=全部)")
    parser.add_argument("--headless", action="store_true", default=False,
                        help="阿里用无头模式(需已登录 profile)")
    parser.add_argument("--workers", type=int, default=3,
                        help="每个源的并行标签页数(固定数量复用,默认 3;不逐条开新标签)")
    parser.add_argument("--reparse-description", action="store_true", default=False,
                        help="对已存整篇描述(仍含「拍卖标的」)按分段规则重提取回填,不开浏览器;无法分段的打印链接")
    args = parser.parse_args()
    sources = ["ali", "gpai"] if args.source == "all" else [args.source]
    if args.reparse_description:
        total = _run_reparse(sources, args.limit)
    else:
        total = asyncio.run(_amain(sources, args.limit, args.headless, args.workers))
    print(f"完成,共补填 {total} 条", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())