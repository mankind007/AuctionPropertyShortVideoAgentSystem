"""utils.description.extract_auction_description 契约测试(docs/初步信息 第15/65行规则)。"""
from __future__ import annotations

from utils.description import extract_auction_description, extract_property_info


def test_extract_between_marker_and_nearest_header():
    raw = ("河南省郑州市中级人民法院委托拍卖\n"
           "拍卖标的：河南省郑州市某房产\n"
           "产权证号：XXXX\n"
           "二、拍卖程序\n"
           "三、竞买须知")
    out = extract_auction_description(raw)
    assert "二、" not in out
    assert "拍卖标的：" not in out
    assert "河南省郑州市某房产" in out
    assert "产权证号：XXXX" in out


def test_ascii_colon_marker_and_non_two_header():
    raw = ("拍卖标的物:某商业用房\n"
           "坐落于人民路一号\n"
           "三、拍卖方式")
    out = extract_auction_description(raw)
    assert "三、" not in out
    assert "某商业用房" in out
    assert "人民路一号" in out


def test_nearest_header_is_yi():
    raw = ("公告说明\n拍卖标的：某住宅\n"
           "建筑面积约120平\n"
           "一、拍卖标的基本情况\n"
           "二、竞买人条件")
    out = extract_auction_description(raw)
    assert "一、" not in out
    assert "某住宅" in out
    assert "建筑面积约120平" in out


def test_no_marker_returns_raw():
    raw = "无标记的普通文本段落,原样返回即可。"
    assert extract_auction_description(raw) == raw.strip()


def test_no_marker_not_mis_cut_by_header():
    raw = "法院公告全文\n一、基本信息\n二、拍卖流程\n三、竞买须知"
    assert extract_auction_description(raw) == raw.strip()


def test_new_rule_numbered_sections():
    raw = ("第一条 拍卖标的：二七区长江中路128号北区五期11号楼东3单元2层27号（不动产权证号：0601045386），"
           "房产建筑面积为137.67㎡，总层数6层，所在层数2层，朝向为南北朝向，"
           "配套：通路、通电、通讯、通上水、通下水、通燃气、通暖气，房屋现状以实地查勘为准。\n\n"
           "第二条 拍卖标的信息披露：有抵押权人；无优先购买权人。\n\n"
           "第三条 拍卖价格信息：评估价：1320300元，起拍价：1010029.5元，保证金：200000元，增价幅度：5000元。\n\n"
           "第四条 竞买人条件：凡具备完全民事行为能力的自然人、法人和其他组织均可参加竞买。")
    out = extract_auction_description(raw)
    assert "第一条" in out
    assert "二七区长江中路128号" in out
    assert "第二条" not in out
    assert "评估价" not in out
    assert "\n" not in out
    assert out.strip() == out


def test_new_rule_arabic_section_up_to_next():
    raw = "成交说明\n第1条 拍卖标的：某房产位于朝阳路\n房屋类型为住宅\n第2条 其他说明：无\n第3条 保证金"
    out = extract_auction_description(raw)
    assert "第1条" in out
    assert "朝阳路" in out
    assert "第2条" not in out
    assert "\n" not in out


def test_new_rule_spaces_around_number():
    raw = "第 1 条 拍卖标的：某住宅位于幸福路\n五楼朝南\n第 2条 说明：无\n第3 条 保证金"
    out = extract_auction_description(raw)
    assert "幸福路" in out
    assert "五楼朝南" in out
    assert "说明：无" not in out
    assert "保证金" not in out
    assert "\n" not in out


def test_empty_returns_empty():
    assert extract_auction_description("") == ""
    assert extract_auction_description(None) == ""


def test_too_short_segment_falls_back_to_raw():
    raw = "拍卖标的：很短\n二、拍卖程序\n随便一点内容"
    assert extract_auction_description(raw) == raw.strip()


def test_property_info_full_block_until_next_section():
    raw = ("标的物属性\n"
           "流转方式：\n转让 \n"
           "物业类型：\n住宅用房 \n"
           "朝向：\n东北 \n"
           "建筑面积：\n96.91 平方米 \n"
           "标的物详情描述\n"
           "【标的物详情】\n拍品名称：某某")
    out = extract_property_info(raw)
    assert isinstance(out, dict)
    assert out == {"流转方式": "转让", "物业类型": "住宅用房",
                   "朝向": "东北", "建筑面积": "96.91 平方米"}
    assert "标的物详情描述" not in str(out)
    assert "拍品名称" not in str(out)


def test_property_info_inline_key_value_and_multiline_value():
    raw = ("标的物属性\n"
           "流转方式：转让\n"
           "物业类型：\n住宅用房\n建筑面积：\n96.91 平方米\n"
           "其他说明：\n该标的\n分期支付\n"
           "竞买人条件不明")
    out = extract_property_info(raw)
    assert out["流转方式"] == "转让"
    assert out["物业类型"] == "住宅用房"
    assert out["其他说明"] == "该标的 分期支付"
    assert len(out) == 4


def test_property_info_missing_returns_empty():
    assert extract_property_info("无该区块的普通文本") == {}
    assert extract_property_info("") == {}
    assert extract_property_info(None) == {}