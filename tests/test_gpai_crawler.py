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
    return mod.to_int_price, mod.extract_time, mod.item_url, mod._parse_listing


@pytest.fixture(scope="module")
def funcs():
    return _build_parse_func()


# ---------------------------------------------------------------------------
# 价格解析
# ---------------------------------------------------------------------------

def test_price_yuan(funcs):
    to_int_price, *_ = funcs
    assert to_int_price("750000") == 750000.0
    assert to_int_price("842295.44 元") == 842295.44
    assert to_int_price("1,504,099 元") == 1504099.0


def test_price_wan_yuan(funcs):
    to_int_price, *_ = funcs
    assert to_int_price("94.43万元") == 944300.0


def test_price_qian_yuan(funcs):
    to_int_price, *_ = funcs
    assert to_int_price("500千元") == 500000.0


def test_price_bai_yuan(funcs):
    to_int_price, *_ = funcs
    assert to_int_price("800百元") == 80000.0


def test_price_shi_wan_yuan(funcs):
    to_int_price, *_ = funcs
    assert to_int_price("3十万元") == 300000.0


def test_price_bai_wan_yuan(funcs):
    to_int_price, *_ = funcs
    assert to_int_price("2.5百万元") == 2500000.0


def test_price_yi_yuan(funcs):
    to_int_price, *_ = funcs
    assert to_int_price("9.09亿元") == 909000000.0


def test_price_shi_yi_yuan(funcs):
    to_int_price, *_ = funcs
    assert to_int_price("1.5十亿元") == 1500000000.0


def test_price_invalid(funcs):
    to_int_price, *_ = funcs
    assert to_int_price("") is None
    assert to_int_price("无") is None


# ---------------------------------------------------------------------------
# 时间提取
# ---------------------------------------------------------------------------

def test_extract_time(funcs):
    _, extract_time, *_ = funcs
    assert extract_time("预计成交时间：2026-8-13 10:00:00") == "2026-8-13 10:00:00"
    assert extract_time("开始时间：2026-08-13 10:00") == "2026-08-13 10:00"


def test_extract_time_none(funcs):
    _, extract_time, *_ = funcs
    assert extract_time("无时间") is None
    assert extract_time("") is None


# ---------------------------------------------------------------------------
# 链接补全
# ---------------------------------------------------------------------------

def test_item_url_fragment(funcs):
    _, _, item_url, *_ = funcs
    assert item_url("//www.gpai.net/sf/item2.do?Web_Item_ID=52886") == \
        "https://www.gpai.net/sf/item2.do?Web_Item_ID=52886"


def test_item_url_full(funcs):
    _, _, item_url, *_ = funcs
    assert item_url("https://www.gpai.net/sf/item2.do?Web_Item_ID=52886") == \
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
    from app.schemas.listing import GpaiCrawlResult
    r = GpaiCrawlResult(restate=1, total=0)
    d = r.to_dict()
    assert set(d) == {"restate", "total", "listings", "details", "errors"}
    assert isinstance(d["listings"], list)
    assert isinstance(d["errors"], list)


# ---------------------------------------------------------------------------
# 标的物介绍表格拍扁(property_info)
# ---------------------------------------------------------------------------

from utils.description import extract_gpai_property_info  # noqa: E402

def _T(rows, title=True):
    """把 (text, colspan, rowspan) 元组行序列拼成 HTML 表格字符串。"""
    body = ""
    for row in rows:
        tr = ""
        for t, cs, rs in row:
            attrs = ""
            if cs > 1:
                attrs += f' colspan="{cs}"'
            if rs > 1:
                attrs += f' rowspan="{rs}"'
            tr += f"<td{attrs}>{t}</td>"
        body += f"<tr>{tr}</tr>"
    return f"<table>{body}</table>"


def test_property_info_two_col():
    """两列 label/value, 值列 colspan=2。"""
    html = _T([
        [("调查情况表", 3, 1)],
        [("标的名称", 1, 1), ("某某路103室", 2, 1)],
        [("权利来源", 1, 1), ("司法裁定", 2, 1)],
        [("建筑面积", 1, 1), ("134.79㎡", 2, 1)],
    ])
    out = extract_gpai_property_info(html, "")
    assert out["标的名称"] == "某某路103室"
    assert out["建筑面积"] == "134.79㎡"
    assert "调查情况表" not in out  # 标题行丢弃


def test_property_info_rowspan_group():
    """rowspan 分组: 组名丢弃, 子键/值保留。"""
    html = _T([
        [("拍品现状", 1, 3), ("用途", 1, 1), ("办公用房", 1, 1)],
        [("建筑面积", 1, 1), ("134.79㎡", 1, 1)],
        [("朝向", 1, 1), ("南", 1, 1)],
        [("提供的文件", 1, 1), ("1.《法院裁定书》", 2, 1)],
    ])
    out = extract_gpai_property_info(html, "")
    assert out["用途"] == "办公用房"
    assert out["建筑面积"] == "134.79㎡"
    assert "拍品现状" not in out
    assert out["提供的文件"].startswith("1.")


def test_property_info_group_single_value():
    """rowspan 组名 + 单值(无子键), 保留 {组名: 值}。"""
    html = _T([
        [("权利限制情况", 1, 2), ("被人民法院查封", 3, 1)],
        [("抵押", 1, 1), ("有", 3, 1)],
    ])
    out = extract_gpai_property_info(html, "")
    assert out["权利限制情况"] == "被人民法院查封"
    assert out["抵押"] == "有"


def test_property_info_multi_row_table():
    """多列多行(53063 权证表): 行首标识做前缀键, 多套房产不覆盖。"""
    html = _T([
        [("房地产权证号", 1, 1), ("幢号和部位", 1, 1), ("建筑面积", 1, 1), ("房屋类型", 1, 1)],
        [("宝2014021219", 1, 1), ("779弄53号301室", 1, 1), ("67.33", 1, 1), ("公寓", 1, 1)],
        [("宝2014021214", 1, 1), ("779弄53号401室", 1, 1), ("89.74", 1, 1), ("公寓", 1, 1)],
    ])
    out = extract_gpai_property_info(html, "")
    assert out["建筑面积_779弄53号301室"] == "67.33"
    assert out["建筑面积_779弄53号401室"] == "89.74"
    assert out["房地产权证号_779弄53号301室"] == "宝2014021219"
    assert out["房屋类型_779弄53号401室"] == "公寓"


def test_property_info_area_fallback_announce():
    """表内无面积 → 回退公告段落。"""
    html = _T([
        [("标的名称", 1, 1), ("某某房产", 2, 1)],
    ])
    announce = "房屋结构：混合，建筑面积：117.12平方米，不动产权证号：20210033953。"
    out = extract_gpai_property_info(html, announce)
    assert out["建筑面积"] == "117.12平方米"
    assert out["标的名称"] == "某某房产"


def test_property_info_area_fallback_intro():
    """表内/公告均无面积 → 回退标的物介绍段落(53061 形态)。"""
    html = _T([
        [("标的名称", 1, 1), ("某某房屋", 2, 1)],
    ])
    intro = "拍品现状用途公寓面积91.49平方米使用情况被执行人在内居住。"
    out = extract_gpai_property_info(html, "起拍价：787025元 保证金：80000元", intro)
    assert out["建筑面积"] == "91.49平方米"


def test_property_info_empty():
    """无结构化表返回 {}。"""
    assert extract_gpai_property_info("", "") == {}
    assert extract_gpai_property_info("<p>无表格</p>", "") == {}