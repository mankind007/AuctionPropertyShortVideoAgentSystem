"""gpai-crawler 契约测试。

优先验证输入/输出结构稳定性,不做网络请求。
对真实页面结构敏感的部分用解析纯函数测试(喂 HTML 片段)。
"""
from __future__ import annotations

import sys

import pytest


def _build_parse_func():
    """从 crawler 模块中取出被测纯函数(skill 目录名带连字符,需按文件路径加载)。"""
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    mod_path = root / "skills" / "gpai-crawler" / "scripts" / "crawler.py"
    spec = importlib.util.spec_from_file_location("gpai_crawler", mod_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._to_int_price, mod._extract_time, mod._item_url, mod._parse_listing


@pytest.fixture(scope="module")
def funcs():
    return _build_parse_func()


# ---------------------------------------------------------------------------
# 价格解析
# ---------------------------------------------------------------------------

def test_price_yuan(funcs):
    _to_int_price, *_ = funcs
    assert _to_int_price("750000") == 750000.0
    assert _to_int_price("842295.44 元") == 842295.44
    assert _to_int_price("1,504,099 元") == 1504099.0


def test_price_wan_yuan(funcs):
    _to_int_price, *_ = funcs
    assert _to_int_price("94.43万元") == 944300.0


def test_price_qian_yuan(funcs):
    _to_int_price, *_ = funcs
    assert _to_int_price("500千元") == 500000.0


def test_price_bai_yuan(funcs):
    _to_int_price, *_ = funcs
    assert _to_int_price("800百元") == 80000.0


def test_price_shi_wan_yuan(funcs):
    _to_int_price, *_ = funcs
    assert _to_int_price("3十万元") == 300000.0


def test_price_bai_wan_yuan(funcs):
    _to_int_price, *_ = funcs
    assert _to_int_price("2.5百万元") == 2500000.0


def test_price_yi_yuan(funcs):
    _to_int_price, *_ = funcs
    assert _to_int_price("9.09亿元") == 909000000.0


def test_price_shi_yi_yuan(funcs):
    _to_int_price, *_ = funcs
    assert _to_int_price("1.5十亿元") == 1500000000.0


def test_price_invalid(funcs):
    _to_int_price, *_ = funcs
    assert _to_int_price("") is None
    assert _to_int_price("无") is None


# ---------------------------------------------------------------------------
# 时间提取
# ---------------------------------------------------------------------------

def test_extract_time(funcs):
    _, _extract_time, *_ = funcs
    assert _extract_time("预计成交时间：2026-8-13 10:00:00") == "2026-8-13 10:00:00"
    assert _extract_time("开始时间：2026-08-13 10:00") == "2026-08-13 10:00"


def test_extract_time_none(funcs):
    _, _extract_time, *_ = funcs
    assert _extract_time("无时间") is None
    assert _extract_time("") is None


# ---------------------------------------------------------------------------
# 链接补全
# ---------------------------------------------------------------------------

def test_item_url_fragment(funcs):
    _, _, _item_url, *_ = funcs
    assert _item_url("//www.gpai.net/sf/item2.do?Web_Item_ID=52886") == \
        "https://www.gpai.net/sf/item2.do?Web_Item_ID=52886"


def test_item_url_full(funcs):
    _, _, _item_url, *_ = funcs
    assert _item_url("https://www.gpai.net/sf/item2.do?Web_Item_ID=52886") == \
        "https://www.gpai.net/sf/item2.do?Web_Item_ID=52886"


# ---------------------------------------------------------------------------
# 列表项解析(用模拟 locator 喂真实结构的简化节点)
# ---------------------------------------------------------------------------

class _FakeLocator:
    """模拟 playwright locator: 支持 .first/.count/.all()/inner_text/get_attribute/all_inner_texts。"""

    def __init__(self, texts=None, href=None, count=0):
        self._texts = texts if texts is not None else []
        self._href = href
        self._count = count

    @property
    def first(self):
        if self._texts or self._href:
            return _FakeLocator(
                texts=self._texts[:1],
                href=self._href,
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


class _FakeNode:
    """模拟列表项节点,按 XPath 关键词分发子 locator。"""

    def __init__(self, title, href, price, eval_text, time_text, time_label="开始时间",
                 eval_label="评估价"):
        self._data = {
            "tit": (title, href),
            "infos": [
                f"起拍价：{price}元",
                f"{eval_label}：{eval_text}",
                f"{time_label}：{time_text}",
            ],
        }
    def locator(self, xp):
        if "item-tit" in xp:
            return _FakeLocator(texts=[self._data["tit"][0]], href=self._data["tit"][1])
        if "gpai-infos" in xp:
            return _FakeLocator(texts=list(self._data["infos"]))
        return _FakeLocator()


def _make_item_node(title, href, price, eval_text, time_text, time_label="开始时间",
                    eval_label="评估价"):
    return _FakeNode(title, href, price, eval_text, time_text,
                     time_label=time_label, eval_label=eval_label)


def test_parse_listing_full(funcs):
    _, _, _, _parse_listing = funcs
    node = _make_item_node(
        title="上海黄浦区某某路352弄39号103室",
        href="//www.gpai.net/sf/item2.do?Web_Item_ID=52886",
        price="750000",
        eval_text="94.43万元",
        time_text="2026-8-13 10:00:00",
    )
    l = _parse_listing(node)
    assert l.item_id == "52886"
    assert l.title == "上海黄浦区某某路352弄39号103室"
    assert l.start_price == 750000.0
    assert l.ref_price == 944300.0
    assert l.ref_price_type == "评估价"
    assert l.start_time == "2026-8-13 10:00:00"
    assert l.crawled_at is not None
    assert l.url == "https://www.gpai.net/sf/item2.do?Web_Item_ID=52886"


def test_parse_listing_market_price(funcs):
    """参考价标签可为 市场价(ref_price_type 正确记录)。"""
    _, _, _, _parse_listing = funcs
    node = _make_item_node(
        title="上海某标的",
        href="//www.gpai.net/sf/item2.do?Web_Item_ID=53001",
        price="500000",
        eval_text="600万元",
        time_text="2026-8-30 10:00:00",
        eval_label="市场价",
    )
    l = _parse_listing(node)
    assert l.ref_price_type == "市场价"
    assert l.start_time == "2026-8-30 10:00:00"
    assert l.crawled_at is not None


# ---------------------------------------------------------------------------
# 结果结构契约(直接验证 schema)
# ---------------------------------------------------------------------------

def test_schema_structure(funcs):
    from src.schemas.listing import GpaiCrawlResult
    r = GpaiCrawlResult(restate=1, total=0)
    d = r.to_dict()
    assert set(d) == {"restate", "total", "listings", "details", "errors"}
    assert isinstance(d["listings"], list)
    assert isinstance(d["errors"], list)
