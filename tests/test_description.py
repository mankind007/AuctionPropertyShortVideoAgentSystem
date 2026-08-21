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


def test_clean_property_info_uses_chinese_core_keys():
    """clean_property_info 提取到 _core 的键必须是中文规范键, 而非旧英文键。"""
    from utils.description import clean_property_info
    info = {
        "建筑面积": "88.35平方米",
        "不动产权证号": "粤（2018）深圳市不动产权第0026444号",
        "权利人": "韦金爱",
        "房屋用途": "住宅",
        "起拍价": "人民币2127581.09元",
        "评估价": "人民币3324345.45元",
    }
    core = clean_property_info(info)
    assert "建筑面积" in core and core["建筑面积"] == "88.35平方米"
    assert "不动产权证号" in core
    assert "权利人" in core and core["权利人"] == "韦金爱"
    assert "房屋用途" in core
    # 起拍价/评估价 细分键各自独立
    assert "起拍价" in core and "评估价" in core
    # 不得出现旧英文键
    assert "area" not in core and "property_cert" not in core and "owner" not in core


def test_clean_property_info_preserves_multiple_area_types():
    """多个面积类型(建筑面积/套内面积/土地面积)应各自保留, 不互相覆盖。"""
    from utils.description import clean_property_info
    info = {
        "建筑面积": "100平方米",
        "套内面积": "80平方米",
        "土地面积": "50平方米",
    }
    core = clean_property_info(info)
    assert core.get("建筑面积") == "100平方米"
    assert core.get("套内面积") == "80平方米"
    assert core.get("土地面积") == "50平方米"


def test_clean_listing_data_unit_normalized():
    """clean_listing_data 应将面积单位统一为「平方米」。"""
    from utils.description import clean_listing_data
    data = {
        "property_info": {
            "建筑面积": "88.35㎡",
            "不动产权证号": "粤（2018）深圳市不动产权第0026444号",
        }
    }
    out = clean_listing_data(data)
    assert out["_core"]["建筑面积"] == "88.35平方米"


def test_extract_from_desc_colon_pairs():
    """description 中的 `键：值` 冒号对(土地用途/房屋结构/保证金/加价幅度等)应被提取。"""
    from utils.description import _extract_from_desc
    desc = (
        "标的物坐落：昆明市官渡区季宏路31号 "
        "建筑面积：59.6平方米 土地用途：城镇住宅用地 权利性质：出让 "
        "房屋结构：钢筋混凝土结构 起拍价：26500元 "
        "保证金：4200元 加价幅度：42元 房屋取得方式：买卖 总层数：11 所在楼层：5"
    )
    fields = _extract_from_desc(desc)
    assert fields.get("土地用途") == "城镇住宅用地"
    assert fields.get("土地性质") == "出让"          # 权利性质 -> 土地性质
    assert fields.get("房屋结构") == "钢筋混凝土结构"
    assert fields.get("保证金") == "4200元"
    assert fields.get("加价幅度") == "42元"
    assert fields.get("房屋取得方式") == "买卖"
    assert fields.get("总层数") == "11"
    assert fields.get("所在楼层") == "5"


def test_clean_listing_data_merges_desc_into_core():
    """description 字段应先回灌进 property_info, 再由 property_info 选出 _core(保证 _core ⊆ property_info)。"""
    from utils.description import clean_listing_data
    data = {
        "property_info": {"坐落": "昆明市官渡区季宏路31号", "建筑面积": "59.6平方米"},
        "description": (
            "土地用途：城镇住宅用地 房屋结构：钢筋混凝土结构 "
            "保证金：4200元 加价幅度：42元"
        ),
    }
    out = clean_listing_data(data)
    core = out["_core"]
    info = out["property_info"]
    assert core["建筑面积"] == "59.6平方米"          # property_info 优先
    assert core["坐落"] == "昆明市官渡区季宏路31号"
    assert core["土地用途"] == "城镇住宅用地"         # 来自 description, 回灌进 info 后再入选
    assert core["房屋结构"] == "钢筋混凝土结构"
    assert core["保证金"] == "4200元"
    assert core["加价幅度"] == "42元"
    # _core 必须是 property_info 的子集
    assert set(core.keys()).issubset(set(info.keys()))
    # description 提取的字段已并入 property_info(全集)
    assert info["土地用途"] == "城镇住宅用地"
    assert out["_cleaned"] is True
