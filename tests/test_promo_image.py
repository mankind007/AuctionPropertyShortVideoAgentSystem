import importlib.util
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

_spec = importlib.util.spec_from_file_location(
    "compose", PROJ / "skills/promo-image/scripts/compose.py")
compose = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compose)

_parse_script = compose._parse_script
_assign_angles = compose._assign_angles


def test_parse_script_angles_and_order():
    """契约: data.script 文本 → {角度: 文案}, 保持出现顺序。"""
    s = "【开场钩子】A\n【价格解析】B\n【行动号召】C\n"
    assert _parse_script(s) == {"开场钩子": "A", "价格解析": "B", "行动号召": "C"}


def test_parse_script_empty_and_junk():
    """契约: 空/无文案内容返回空 dict, 不抛错。"""
    assert _parse_script("") == {}
    assert _parse_script("【A】【B】") == {}
    assert _parse_script("没有角度的普通文字") == {}


def test_assign_angles_first_last_fixed():
    """契约: 首图=开场钩子, 末图=行动号召, 中间按话术顺序循环。"""
    filled = {"开场钩子": "a", "房源硬指标": "b", "价格解析": "c", "行动号召": "d"}
    for n in (1, 2, 4, 6):
        assigned = _assign_angles(n, filled)
        assert assigned[0] == "开场钩子"
        if n >= 2:
            assert assigned[-1] == "行动号召"
        assert len(assigned) == n


def test_assign_angles_middle_cycle():
    """契约: 图多于角度时中间回卷, 首尾不重复。"""
    filled = {"开场钩子": "a", "房源硬指标": "b", "价格解析": "c", "行动号召": "d"}
    a5 = _assign_angles(5, filled)
    # 中间位置不应连续出现首尾角度
    assert a5[0] == "开场钩子" and a5[-1] == "行动号召"
    assert len(set(a5)) >= 3


def test_expand_images_few():
    """契约: 少图保底4张 — 1图→[A,A,A,A]; 2图→[A,A,B,B]; ≥3图原样。"""
    a, b, c = object(), object(), object()
    assert compose._expand_images([a]) == [a, a, a, a]
    assert compose._expand_images([a, b]) == [a, a, b, b]
    assert compose._expand_images([a, b, c]) == [a, b, c]
    assert len(compose._expand_images(list(range(5)))) == 5


def test_clean_title_strips_brackets():
    """契约: 海报标题剥离 拍次标签与【】[]〔〕括号(含未闭合截断), 保留正文。"""
    clean = compose._clean_title
    assert clean("【一拍】广东省清远市清城区横荷街道打古村") == "广东省清远市清城区横荷街道打古村"
    assert clean("广饶县中南世纪城小区68#楼 [权证号:xxx]") == "广饶县中南世纪城小区68#楼"
    assert clean("深圳市罗湖区笋岗东路〔房地产证号：深房地字第2000") == "深圳市罗湖区笋岗东路"
    assert clean("河北...(2024)香河县宝海道1号") == "河北...(2024)香河县宝海道1号"
    assert clean("") == ""
