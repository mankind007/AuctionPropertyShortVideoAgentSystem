"""ali-assets-crawler 契约测试。

优先验证纯函数/结构稳定性,不做网络请求与登录。
对真实页面结构敏感的部分用假节点(fake locator)测试解析逻辑。
"""
from __future__ import annotations

import sys

import pytest


def _build_funcs():
    """按文件路径加载 ali crawler 模块(skill 目录名带连字符)。"""
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    mod_path = root / "skills" / "ali-assets-crawler" / "scripts" / "crawler.py"
    spec = importlib.util.spec_from_file_location("ali_crawler", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def m():
    return _build_funcs()


# ---------------------------------------------------------------------------
# 价格解析(￥ + 中文单位归一为元)
# ---------------------------------------------------------------------------

def test_price_yuan(m):
    assert m.to_int_price("￥750000") == 750000.0
    assert m.to_int_price("￥ 1,500,000") == 1500000.0
    assert m.to_int_price("750000") == 750000.0


def test_price_units(m):
    assert m.to_int_price("￥800百元") == 80000.0
    assert m.to_int_price("￥500千元") == 500000.0
    assert m.to_int_price("￥94.43万元") == 944300.0
    assert m.to_int_price("￥3十万元") == 300000.0
    assert m.to_int_price("￥2.5百万元") == 2500000.0
    assert m.to_int_price("￥1.5千万元") == 15000000.0
    assert m.to_int_price("￥9.09亿元") == 909000000.0


def test_price_invalid(m):
    assert m.to_int_price("") is None
    assert m.to_int_price(None) is None
    assert m.to_int_price("暂无参考价") is None


# ---------------------------------------------------------------------------
# 图片 URL 修正
# ---------------------------------------------------------------------------

def test_fix_img_src(m):
    assert m._fix_img_src("//img.alicdn.com/pic_80x80.jpg") == \
        "https://img.alicdn.com/pic_960x960.jpg"
    assert m._fix_img_src("https://img.alicdn.com/pic_80x80.jpg") == \
        "https://img.alicdn.com/pic_960x960.jpg"
    # 实测列表封面图后缀 _300x1000
    assert m._fix_img_src("//img.alicdn.com/a.jpg_300x1000") == \
        "https://img.alicdn.com/a.jpg_960x960"


def test_item_url(m):
    assert m.item_url("//sf.taobao.com/item.htm?id=123") == \
        "https://sf.taobao.com/item.htm?id=123"
    assert m.item_url("https://sf.taobao.com/item.htm?id=123") == \
        "https://sf.taobao.com/item.htm?id=123"


def test_extract_item_id(m):
    # 阿里资产 sf_item 链接(实测)
    assert m._extract_item_id("//sf-item.taobao.com/sf_item/1068866243328.htm?track_id=x") == \
        "1068866243328"
    assert m._extract_item_id("https://sf-item.taobao.com/sf_item/52886.htm") == "52886"
    assert m._extract_item_id("https://x.y/z") == ""


# ---------------------------------------------------------------------------
# 列表项解析(用模拟 locator 喂真实结构简化节点)
# ---------------------------------------------------------------------------

class _FakeLocator:
    def __init__(self, texts=None, href=None, count=0):
        self._texts = texts if texts is not None else []
        self._href = href
        self._count = count

    @property
    def first(self):
        if self._texts or self._href:
            return _FakeLocator(
                texts=self._texts[:1], href=self._href,
                count=1 if (self._texts or self._href) else 0,
            )
        return _FakeLocator(count=0)

    def count(self):
        return self._count if self._count else (1 if (self._texts or self._href) else 0)

    def inner_text(self):
        return self._texts[0] if self._texts else ""

    def get_attribute(self, name):
        return self._href

    def all(self):
        return [_FakeLocator(texts=[t]) for t in self._texts]

    def all_inner_texts(self):
        return list(self._texts)


class _FakeItem:
    """模拟单条 li: title / href / 起拍价 / 参考价(可选) / 图片 src 列表。"""

    def __init__(self, title, href, price, ref=None, imgs=()):
        self._title = title
        self._href = href
        self._price = price
        self._ref = ref
        self._imgs = list(imgs)

    def locator(self, xp):
        if "header-section" in xp:
            return _FakeLocator(texts=[self._title])
        if xp.endswith("/a") or "item_href" in xp:
            return _FakeLocator(href=self._href)
        if "price-todo" in xp:
            return _FakeLocator(texts=[self._price])
        if "price-assess" in xp:
            return _FakeLocator(texts=[self._ref] if self._ref else [])
        if "pm-thumb" in xp:
            return _FakeLocator(texts=self._imgs, href=self._imgs[0] if self._imgs else None)
        return _FakeLocator()


def test_parse_listing_full(m):
    node = _FakeItem(
        title="上海市静安区某某路88弄3号502室",
        href="//sf-item.taobao.com/sf_item/1068866243328.htm",
        price="￥750000",
        ref="￥94.43万元",
    )
    l = m._parse_listing(node, "住宅")
    assert l.source == "ali"
    assert l.category == "住宅"
    assert l.item_id == "1068866243328"
    assert l.title == "上海市静安区某某路88弄3号502室"
    assert l.start_price == 750000.0
    assert l.ref_price == 944300.0
    assert l.ref_price_type == "参考价"
    assert l.status == "即将开始"
    assert l.crawled_at is not None
    assert l.url == "https://sf-item.taobao.com/sf_item/1068866243328.htm"


def test_parse_listing_no_ref(m):
    node = _FakeItem(
        title="上海市某某标的",
        href="//sf-item.taobao.com/sf_item/53001.htm",
        price="￥2.5万元",
    )
    l = m._parse_listing(node, "住宅")
    assert l.ref_price is None
    assert l.ref_price_type == ""
    assert l.start_price == 25000.0


# ---------------------------------------------------------------------------
# 结果结构契约(直接验证 schema)
# ---------------------------------------------------------------------------

def test_auction_schema(m):
    from app.schemas.listing import AuctionCrawlResult
    r = AuctionCrawlResult(source="ali", category="住宅", total=5)
    d = r.to_dict()
    assert set(d) == {"source", "category", "total", "listings", "details", "errors"}
    assert d["source"] == "ali"
    assert d["category"] == "住宅"


def test_gpai_schema_compat(m):
    from app.schemas.listing import GpaiCrawlResult
    r = GpaiCrawlResult(restate=1, total=0)
    d = r.to_dict()
    assert set(d) == {"restate", "total", "listings", "details", "errors"}


# ---------------------------------------------------------------------------
# download_images 分批并发契约(x∈{3,4,5} 随机,不足 x 一批全下)
# ---------------------------------------------------------------------------

class _FakeResp:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return b"\xff\xd8fake"


def test_download_images_batch_chunk(m, monkeypatch, tmp_path):
    import random
    import urllib.request
    from app.schemas.listing import AuctionDetail

    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    monkeypatch.setattr(random, "uniform", lambda a, b: 0)

    def _fake_open(req, timeout=None):
        return _FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_open)

    detail = AuctionDetail(source="ali", item_id="111",
                           images=[f"https://img.alicdn.com/i{i}.jpg" for i in range(7)])
    saved = m.download_images(detail, "111", tmp_path)
    assert len(saved) == 7
    assert all(x["file"] for x in saved)
    assert [x["url"] for x in saved] == [f"https://img.alicdn.com/i{i}.jpg" for i in range(7)]
    imgs = sorted(p.name for p in tmp_path.glob("111/imgs/*.jpg"))
    assert imgs == ["01.jpg", "02.jpg", "03.jpg", "04.jpg", "05.jpg", "06.jpg", "07.jpg"]


def test_download_images_less_than_3(m, monkeypatch, tmp_path):
    import random
    import urllib.request
    from app.schemas.listing import AuctionDetail

    monkeypatch.setattr(random, "randint", lambda a, b: 5)
    monkeypatch.setattr(random, "uniform", lambda a, b: 0)

    def _fake_open(req, timeout=None):
        return _FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_open)

    detail = AuctionDetail(source="ali", item_id="222", images=["https://img.alicdn.com/a.jpg"])
    saved = m.download_images(detail, "222", tmp_path)
    assert len(saved) == 1
    assert saved[0]["file"] and (tmp_path / "222/imgs/01.jpg").exists()


def test_download_images_skip_existing(m, monkeypatch, tmp_path):
    import random
    import urllib.request
    from app.schemas.listing import AuctionDetail

    monkeypatch.setattr(random, "randint", lambda a, b: 5)
    monkeypatch.setattr(random, "uniform", lambda a, b: 0)
    calls = []

    def _fake_open(req, timeout=None):
        calls.append(req.full_url)
        return _FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_open)

    imgs_dir = tmp_path / "333" / "imgs"
    imgs_dir.mkdir(parents=True)
    (imgs_dir / "01.jpg").write_bytes(b"\xff\xd8existing")

    detail = AuctionDetail(source="ali", item_id="333",
                           images=["https://img.alicdn.com/i1.jpg", "https://img.alicdn.com/i2.jpg"])
    saved = m.download_images(detail, "333", tmp_path)
    assert len(saved) == 2
    assert [x["file"] for x in saved] == ["01.jpg", "02.jpg"]
    # 已存在的 01.jpg 不应重新下载
    assert calls == ["https://img.alicdn.com/i2.jpg"]


def test_download_images_retry_then_success(m, monkeypatch, tmp_path):
    """单张前 2 次失败、第 3 次成功:重试机制应成功下载。"""
    import random
    import urllib.request
    import utils.download as ud
    from app.schemas.listing import AuctionDetail

    monkeypatch.setattr(random, "randint", lambda a, b: 5)
    monkeypatch.setattr(random, "uniform", lambda a, b: 0)
    monkeypatch.setattr(ud.time, "sleep", lambda s: None)
    attempts = {"n": 0}

    def _flaky_open(req, timeout=None):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise OSError("temporary")
        return _FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", _flaky_open)

    detail = AuctionDetail(source="ali", item_id="444", images=["https://img.alicdn.com/f.jpg"])
    saved = m.download_images(detail, "444", tmp_path)
    assert len(saved) == 1
    assert saved[0]["file"] and attempts["n"] == 3
    assert (tmp_path / "444/imgs/01.jpg").exists()


def test_download_images_retry_exhausted(m, monkeypatch, tmp_path):
    """重试 3 次仍失败:不中断,file 置 None 保留记录。"""
    import random
    import urllib.request
    import utils.download as ud
    from app.schemas.listing import AuctionDetail

    monkeypatch.setattr(random, "randint", lambda a, b: 5)
    monkeypatch.setattr(random, "uniform", lambda a, b: 0)
    monkeypatch.setattr(ud.time, "sleep", lambda s: None)

    def _fail_open(req, timeout=None):
        raise OSError("always")

    monkeypatch.setattr(urllib.request, "urlopen", _fail_open)

    detail = AuctionDetail(source="ali", item_id="555", images=["https://img.alicdn.com/x.jpg"])
    saved = m.download_images(detail, "555", tmp_path)
    assert len(saved) == 1
    assert saved[0]["file"] is None
    assert not (tmp_path / "555/imgs/01.jpg").exists()


def test_parse_ali_start_time(m):
    assert m._parse_ali_start_time("08月15日 10:00") is not None
    assert m._parse_ali_start_time("08月15日 10:00").startswith(str(__import__("datetime").date.today().year))
    assert m._parse_ali_start_time("") is None
    assert m._parse_ali_start_time(" 01月05日 09:30 ") is not None
    assert m._is_near_midnight_deadline("12月31日 23:55") is True
    assert m._is_near_midnight_deadline("12月31日 23:50") is False
    assert m._is_near_midnight_deadline("01月01日 00:00") is False


# ---------------------------------------------------------------------------
# 滑块自动拖动 (_try_auto_slide)
# ---------------------------------------------------------------------------

class _SliderLocator:
    def __init__(self, present=True, box=None):
        self._present = present
        self._box = box

    async def count(self):
        return 1 if self._present else 0

    async def bounding_box(self):
        return self._box


class _SliderMouse:
    def __init__(self):
        self.points = []
        self.down_called = False
        self.up_called = False
        self.on_down = None

    async def move(self, x, y, steps=1):
        self.points.append((x, y))

    async def down(self):
        self.down_called = True
        if self.on_down:
            self.on_down()

    async def up(self):
        self.up_called = True


class _SliderPage:
    """hold 滑块 DOM,url 非验证页;拖动 success 时 DOM 消失。"""

    def __init__(self, box=None, pass_after_drag=False):
        self._box = box or {"x": 0.0, "y": 50.0, "width": 40.0, "height": 36.0}
        self.drag_target = 300.0
        self.pass_after_drag = pass_after_drag
        self.dragged = False
        self.mouse = _SliderMouse()
        self.mouse.on_down = self._mark_dragged

    def _mark_dragged(self):
        self.dragged = True

    @property
    def url(self):
        return "https://sf.taobao.com/list"

    def locator(self, sel):
        if sel == "#nc_1__scale_text, #nc_1_nz1, #nc_1_n1z":
            if self.pass_after_drag and self.dragged:
                return _SliderLocator(present=False)
            return _SliderLocator(present=True)
        if sel in ("#nc_1_nz1, #nc_1_n1z", "#nc_1_nz1", "#nc_1_n1z"):
            return _SliderLocator(present=True, box=self._box)
        if sel == "#nc_1__scale_text":
            return _SliderLocator(present=True, box={"x": 0.0, "y": 50.0, "width": self.drag_target, "height": 36.0})
        return _SliderLocator(present=False)

    async def wait_for_timeout(self, ms):
        pass


class _PassAfterDragPage(_SliderPage):
    pass


def test_dom_blocked_detects_slider(m):
    import asyncio

    page = _SliderPage()
    assert asyncio.run(m._dom_blocked(page)) is True


def test_still_blocked_url_login(m):
    import asyncio

    class _LoginPage:
        url = "https://login.taobao.com/xxx"

        def locator(self, sel):
            return _SliderLocator(present=False)

    assert asyncio.run(m._still_blocked(_LoginPage())) is True


def test_try_auto_slide_success(m, monkeypatch):
    """把手存在、拖动后(触发 mouse.down)DOM 消失 → 自动通过。"""
    import asyncio
    import random

    monkeypatch.setattr(random, "randint", lambda a, b: 5)
    page = _PassAfterDragPage(pass_after_drag=True)
    ok = asyncio.run(m._try_auto_slide(page, max_attempts=2))
    assert ok is True
    assert page.mouse.down_called and page.mouse.up_called


def test_try_auto_slide_no_slider(m):
    import asyncio

    class _CleanPage:
        url = "https://sf.taobao.com/list"

        def locator(self, sel):
            return _SliderLocator(present=False)

    assert asyncio.run(m._try_auto_slide(_CleanPage(), max_attempts=2)) is True


# ---------------------------------------------------------------------------
# STEALTH_SCRIPT 反检测补丁校验
# ---------------------------------------------------------------------------

def test_stealth_patches_canvas():
    """Canvas 微噪默认不注入,显式开启才注入。"""
    from utils.browser import STEALTH_SCRIPT, render_stealth_script
    assert "HTMLCanvasElement.prototype.toDataURL" not in STEALTH_SCRIPT
    script = render_stealth_script(patch_canvas=True)
    assert "HTMLCanvasElement.prototype.toDataURL" in script
    assert "CanvasRenderingContext2D.prototype.getImageData" in script


def test_stealth_patches_webgl():
    from utils.browser import STEALTH_SCRIPT
    assert "WebGLRenderingContext.prototype" in STEALTH_SCRIPT
    assert "37446" in STEALTH_SCRIPT  # UNMASKED_RENDERER_WEBGL
    assert "WEBGL_debug_renderer_info" in STEALTH_SCRIPT


def test_stealth_patches_audiocontext():
    from utils.browser import STEALTH_SCRIPT
    assert "AudioBuffer.prototype.getChannelData" in STEALTH_SCRIPT


def test_stealth_patches_navigator():
    """默认不覆盖 platform/userAgent;显式开启才注入。"""
    from utils.browser import STEALTH_SCRIPT, render_stealth_script
    assert "navigator" in STEALTH_SCRIPT
    assert "'webdriver'" in STEALTH_SCRIPT
    # 默认不注入 platform / userAgent patch
    assert "navigator, 'platform'" not in STEALTH_SCRIPT
    assert "navigator, 'userAgent'" not in STEALTH_SCRIPT
    # 显式开启才注入
    script = render_stealth_script(patch_platform=True, patch_ua=True)
    assert "navigator, 'platform'" in script
    assert "navigator, 'userAgent'" in script
    assert "'Win32'" in script


def test_stealth_cdp_cleanup_off_by_default():
    """CDP 泄露变量清理默认不注入(部分站点检测 chrome 删除反而更可疑)。"""
    from utils.browser import STEALTH_SCRIPT, render_stealth_script
    assert "cdc_ado" not in STEALTH_SCRIPT
    assert "cdc_scripting" not in STEALTH_SCRIPT
    # 显式启用时才注入
    script = render_stealth_script(clean_cdp=True)
    assert "delete window.cdc_ado" in script
    assert "delete window.cdc_scripting" in script
    # 占位符已替换,不残留
    assert "%CDP_CLEANUP%" not in script
    assert "%CDP_CLEANUP%" not in STEALTH_SCRIPT


def test_browser_profile_pool():
    """指纹池有多个候选,UA 各不相同。"""
    from utils.browser import BROWSER_PROFILES
    assert len(BROWSER_PROFILES) >= 3
    uas = {p["ua"] for p in BROWSER_PROFILES}
    assert len(uas) == len(BROWSER_PROFILES)


def test_get_profile_random():
    import utils.browser as b
    seen = set()
    for _ in range(20):
        seen.add(b.get_profile()["ua"])
    # 至少返回 2 个不同 UA(概率极低返回同一个)
    assert len(seen) >= 2


def test_render_stealth_script_matches_ua():
    """渲染的 stealth script 里 navigator.userAgent 应与传入 UA 一致。"""
    from utils.browser import render_stealth_script
    ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    script = render_stealth_script(ua=ua, patch_ua=True)
    assert ua in script
    # userAgentData brands 也应带对应大版本
    assert "124" in script
    assert "%UA%" not in script  # 占位已替换


def test_render_stealth_script_default_no_placeholders():
    from utils.browser import STEALTH_SCRIPT
    assert "%UA%" not in STEALTH_SCRIPT
    assert "%CHROME_MAJOR%" not in STEALTH_SCRIPT
    assert "%CORES%" not in STEALTH_SCRIPT
    assert "%PLATFORM_PATCH%" not in STEALTH_SCRIPT
    assert "%UA_PATCH%" not in STEALTH_SCRIPT
    assert "%CANVAS_PATCH%" not in STEALTH_SCRIPT


# ---------------------------------------------------------------------------
# 新 data 结构契约: images:[{url,file|null}]、raw 去 href/title、无 assets_dir
# ---------------------------------------------------------------------------

def test_download_images_structured_order(m, monkeypatch, tmp_path):
    """下载返回 [{url,file}],顺序与 images 一致,失败 file=None。"""
    import random
    import urllib.request
    from app.schemas.listing import AuctionDetail

    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    monkeypatch.setattr(random, "uniform", lambda a, b: 0)
    fail = {"u": "https://img.alicdn.com/fail.jpg"}

    def _fake_open(req, timeout=None):
        if req.full_url == fail["u"]:
            raise OSError("boom")
        return _FakeResp()

    monkeypatch.setattr(urllib.request, "urlopen", _fake_open)

    detail = AuctionDetail(source="ali", item_id="666",
                           images=["https://img.alicdn.com/ok1.jpg", fail["u"],
                                   "https://img.alicdn.com/ok2.jpg"])
    saved = m.download_images(detail, "666", tmp_path)
    assert [x["url"] for x in saved] == detail.images
    assert [x["file"] for x in saved] == ["01.jpg", None, "03.jpg"]
    assert detail.image_files == ["01.jpg", None, "03.jpg"]


def test_gpai_download_images_structured(m, monkeypatch, tmp_path):
    """gpai 下载同样返回 [{url,file}],命名带扩展名。"""
    import importlib.util
    import random
    import urllib.request
    from pathlib import Path
    from app.schemas.listing import AuctionDetail

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "gpai_crawler", root / "skills" / "gpai-crawler" / "scripts" / "crawler.py")
    gm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gm)

    monkeypatch.setattr(random, "randint", lambda a, b: 4)
    monkeypatch.setattr(random, "uniform", lambda a, b: 0)
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=None: _FakeResp())

    detail = AuctionDetail(source="gpai", item_id="777",
                           images=["https://imgcdn.gpai.net/upload/2026-7/a.jpg"])
    saved = gm.download_images(detail, "777", tmp_path)
    assert len(saved) == 1
    assert saved[0]["file"] == "01.jpg"
    assert detail.image_files == ["01.jpg"]


def test_goto_with_retry_ok_and_fail(m, monkeypatch):
    """网络重试: 短暂失败后成功返回 True;一直失败也持续等待不崩溃。"""
    import asyncio
    import utils.network as net

    calls = {"n": 0}

    class _Page:
        def __init__(self, fail_times):
            self._fail_times = fail_times

        async def goto(self, url, timeout=45000, wait_until="domcontentloaded"):
            calls["n"] += 1
            if calls["n"] <= self._fail_times:
                raise TimeoutError("net down")
            return None

        async def wait_for_timeout(self, ms):
            return None

    async def _no_sleep(s):
        return None

    monkeypatch.setattr(net.asyncio, "sleep", _no_sleep)
    ok = asyncio.run(net.goto_with_retry(_Page(fail_times=2), "https://x", wait_ms=0))
    assert ok is True


# ---------------------------------------------------------------------------
# merge_db_data: 标题变化重建 / 标题相同 merge 保留旧字段
# ---------------------------------------------------------------------------

def _detail(**kw):
    from app.schemas.listing import AuctionDetail
    d = AuctionDetail(source="ali", item_id="666")
    for k, v in kw.items():
        setattr(d, k, v)
    return d


def test_merge_db_data_title_same_keeps_old(m):
    """标题相同: 以旧 data 为底,仅覆盖本次抓到的字段,缺的描述/属性保留。"""
    rec = {"title": "老标题", "data": {"description": "旧描述", "property_info": {"用途": "住宅"},
                                        "images": [], "poi": None}}
    detail = _detail(images=["https://x.jpg"], description="新描述")
    detail.image_files = ["01.jpg"]
    out = m.merge_db_data("老标题", rec, [{"url": "https://x.jpg", "file": "01.jpg"}], detail)
    assert out["description"] == "新描述"
    assert out["property_info"] == {"用途": "住宅"}  # 本次没抓到,保留旧值
    assert out["images"] == [{"url": "https://x.jpg", "file": "01.jpg"}]


def test_merge_db_data_title_changed_rebuilds(m):
    """标题变化 = 新数据: data 清空重建,不保留旧字段与 _empty。"""
    rec = {"title": "旧标题",
           "data": {"description": "旧", "property_info": {}, "images": [], "_empty": True}}
    detail = _detail(images=["https://y.jpg"], description="新")
    detail.image_files = ["02.jpg"]
    out = m.merge_db_data("新标题", rec, [{"url": "https://y.jpg", "file": "02.jpg"}], detail)
    assert out == {"images": [{"url": "https://y.jpg", "file": "02.jpg"}], "description": "新"}
    assert "_empty" not in out and "property_info" not in out


def test_merge_db_data_no_rec_fresh(m):
    """无旧记录: 全新 data,只含本次抓到内容。"""
    detail = _detail(images=["https://z.jpg"])
    detail.image_files = ["03.jpg"]
    out = m.merge_db_data("新", None, [{"url": "https://z.jpg", "file": "03.jpg"}], detail)
    assert out["images"] == [{"url": "https://z.jpg", "file": "03.jpg"}]
    assert "description" not in out


def test_merge_db_data_placeholder_desc_selfheal(m):
    """旧描述为占位且本次未抓到真描述 → merge 时主动删除 description。"""
    rec = {"title": "老", "data": {"description": "公告详情加载中......", "property_info": {"用途": "住宅"}}}
    detail = _detail(images=[])
    out = m.merge_db_data("老", rec, [], detail)
    assert "description" not in out
    assert out["property_info"] == {"用途": "住宅"}


def test_merge_db_data_real_desc_kept(m):
    """旧描述是真实内容且本次未抓到 → 保留(不是占位不清除)。"""
    rec = {"title": "老", "data": {"description": "拍卖标的：真实描述文本", "property_info": {}}}
    detail = _detail(images=[])
    out = m.merge_db_data("老", rec, [], detail)
    assert out["description"] == "拍卖标的：真实描述文本"