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
    assert m._to_int_price("￥750000") == 750000.0
    assert m._to_int_price("￥ 1,500,000") == 1500000.0
    assert m._to_int_price("750000") == 750000.0


def test_price_units(m):
    assert m._to_int_price("￥800百元") == 80000.0
    assert m._to_int_price("￥500千元") == 500000.0
    assert m._to_int_price("￥94.43万元") == 944300.0
    assert m._to_int_price("￥3十万元") == 300000.0
    assert m._to_int_price("￥2.5百万元") == 2500000.0
    assert m._to_int_price("￥1.5千万元") == 15000000.0
    assert m._to_int_price("￥9.09亿元") == 909000000.0


def test_price_invalid(m):
    assert m._to_int_price("") is None
    assert m._to_int_price(None) is None
    assert m._to_int_price("暂无参考价") is None


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
    assert m._item_url("//sf.taobao.com/item.htm?id=123") == \
        "https://sf.taobao.com/item.htm?id=123"
    assert m._item_url("https://sf.taobao.com/item.htm?id=123") == \
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
    l = m._parse_listing(node)
    assert l.source == "ali"
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
    l = m._parse_listing(node)
    assert l.ref_price is None
    assert l.ref_price_type == ""
    assert l.start_price == 25000.0


# ---------------------------------------------------------------------------
# 结果结构契约(直接验证 schema)
# ---------------------------------------------------------------------------

def test_auction_schema(m):
    from src.schemas.listing import AuctionCrawlResult
    r = AuctionCrawlResult(source="ali", category="住宅", total=5)
    d = r.to_dict()
    assert set(d) == {"source", "category", "total", "listings", "details", "errors"}
    assert d["source"] == "ali"
    assert d["category"] == "住宅"


def test_gpai_schema_compat(m):
    from src.schemas.listing import GpaiCrawlResult
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
    from src.schemas.listing import AuctionDetail

    monkeypatch.setattr(random, "randint", lambda a, b: 4)

    def _fake_open(req, timeout=None):
        return _FakeResp()

    monkeypatch.setattr(m.urllib.request, "urlopen", _fake_open)

    detail = AuctionDetail(source="ali", item_id="111",
                           images=[f"https://img.alicdn.com/i{i}.jpg" for i in range(7)])
    saved = m.download_images(detail, "111", tmp_path)
    assert len(saved) == 7
    imgs = sorted(p.name for p in tmp_path.glob("111/imgs/*.jpg"))
    assert imgs == ["01.jpg", "02.jpg", "03.jpg", "04.jpg", "05.jpg", "06.jpg", "07.jpg"]


def test_download_images_less_than_3(m, monkeypatch, tmp_path):
    import random
    from src.schemas.listing import AuctionDetail

    monkeypatch.setattr(random, "randint", lambda a, b: 5)

    def _fake_open(req, timeout=None):
        return _FakeResp()

    monkeypatch.setattr(m.urllib.request, "urlopen", _fake_open)

    detail = AuctionDetail(source="ali", item_id="222", images=["https://img.alicdn.com/a.jpg"])
    saved = m.download_images(detail, "222", tmp_path)
    assert len(saved) == 1
    assert (tmp_path / "222/imgs/01.jpg").exists()


def test_download_images_skip_existing(m, monkeypatch, tmp_path):
    import random
    from src.schemas.listing import AuctionDetail

    monkeypatch.setattr(random, "randint", lambda a, b: 5)
    calls = []

    def _fake_open(req, timeout=None):
        calls.append(req.full_url)
        return _FakeResp()

    monkeypatch.setattr(m.urllib.request, "urlopen", _fake_open)

    imgs_dir = tmp_path / "333" / "imgs"
    imgs_dir.mkdir(parents=True)
    (imgs_dir / "01.jpg").write_bytes(b"\xff\xd8existing")

    detail = AuctionDetail(source="ali", item_id="333",
                           images=["https://img.alicdn.com/i1.jpg", "https://img.alicdn.com/i2.jpg"])
    saved = m.download_images(detail, "333", tmp_path)
    assert len(saved) == 2
    # 已存在的 01.jpg 不应重新下载
    assert calls == ["https://img.alicdn.com/i2.jpg"]