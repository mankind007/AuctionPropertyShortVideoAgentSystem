"""description → 结构化字段 提取效果测试(可独立运行展示)。

    python tests/test_description_to_structured.py
 或 pytest tests/test_description_to_structured.py -v

数据样本在 tests/test_description_samples.json(真实公告文本形态)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.description import extract_description_fields  # noqa: E402

SAMPLE_FILE = Path(__file__).resolve().parent / "test_description_samples.json"


def load_samples() -> list[dict]:
    return json.loads(SAMPLE_FILE.read_text(encoding="utf-8"))


def _fmt(val) -> str:
    if isinstance(val, float):
        return f"{val:g}"
    return str(val)


def test_extract_fields_hit_count() -> None:
    """每个样本至少能提取出 ≥3 个字段, 证明 description 可结构化。"""
    for s in load_samples():
        out = extract_description_fields(s["desc"])
        assert len(out) >= 3, f"{s['id']} 仅提取到 {len(out)} 个字段: {out}"


def test_extract_area_price_type() -> None:
    """关键字段类型: 面积字符串、价格转元数值。"""
    out = extract_description_fields(load_samples()[0]["desc"])
    assert out["建筑面积"] == "137.67㎡"
    assert out["总层数"] == "6"
    assert out["所在层数"] == "2"
    assert out["朝向"] == "南北朝向"
    assert out["不动产权证号"] == "0601045386"
    assert out["房产地址"] == "二七区长江中路128号北区五期11号楼东3单元2层27号"


def test_extract_price_as_number() -> None:
    out = extract_description_fields(load_samples()[2]["desc"])
    assert out["保证金"] == 200000.0
    assert out["增价幅度"] == 10000.0
    assert out["房屋类型"] == "住宅用房"


def test_extract_mortgage_priority() -> None:
    out = extract_description_fields(load_samples()[2]["desc"])
    assert out["抵押信息"] == "有抵押权人"
    assert out["优先购买权"] == "无"


def test_extract_property_info_block() -> None:
    """sample_004 是「标的物属性」区块, extract_property_info 与本函数都能提取。"""
    from utils.description import extract_property_info

    s = load_samples()[3]
    prop = extract_property_info(s["desc"])
    assert prop["物业类型"] == "办公用房"
    assert prop["建筑面积"] == "96.91 平方米"
    out = extract_description_fields(s["desc"])
    assert out.get("物业类型") == "办公用房" or out.get("房屋类型") == "办公用房"


def test_extract_region() -> None:
    """行政区划解析: 省市县区层级, 排除非区域噪声。"""
    out = extract_description_fields(load_samples()[2]["desc"])
    assert out["所在区域"] == "上海市/黄浦区"
    from utils.description import extract_region
    assert extract_region("二七区长江中路128号北区五期") == ["二七区"]
    assert extract_region("位于朝阳市双塔区黄河路") == ["朝阳市", "双塔区"]
    assert extract_region("河北省廊坊市香河县宝海道1号") == ["河北省", "廊坊市", "香河县"]
    assert extract_region("周口市川汇区文昌路北侧") == ["周口市", "川汇区"]


def test_empty_input() -> None:
    assert extract_description_fields("") == {}
    assert extract_description_fields(None) == {}


def test_cert_no_edge_cases() -> None:
    """不动产权证号边界样本: 证明单/字母证号/括号前缀/纯编码, 均须完整无杂质。"""
    cases = {
        "sample_006": "苏（2023）启东市不动产权证明单第0007174号",
        "sample_007": "诸字第F0000085526号",
        "sample_008": "冀（2019）张家口市不动产权第0012640号",
        "sample_009": "广饶20121099",
    }
    samples = {s["id"]: s for s in load_samples()}
    for sid, expect in cases.items():
        out = extract_description_fields(samples[sid]["desc"])
        assert out["不动产权证号"] == expect, f"{sid}: got {out.get('不动产权证号')!r}, want {expect!r}"


def main() -> int:
    print("=== description → 结构化字段 提取效果 ===\n", flush=True)
    for s in load_samples():
        out = extract_description_fields(s["desc"])
        print(f"[{s['id']}]", flush=True)
        print(f"  输入: {s['desc'][:80]}...", flush=True)
        if not out:
            print("  提取: (无)\n", flush=True)
            continue
        for k, v in out.items():
            print(f"  {k}: {_fmt(v)}", flush=True)
        print("", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
