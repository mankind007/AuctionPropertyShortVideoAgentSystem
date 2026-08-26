import importlib.util
import re
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJ))

_spec = importlib.util.spec_from_file_location(
    "generate_scripts", PROJ / "skills/script-writer/scripts/generate_scripts.py")
gs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gs)

fill_templates = gs.fill_templates
extract_fields = gs.extract_fields
_clean_text = gs._clean_text
build_full_script = gs.build_full_script

ANGLE_ORDER = [
    "开场钩子", "房源硬指标", "价格解析", "地段与配套",
    "常见误区", "风险提示", "紧迫感", "行动号召",
]

BASE_FIELDS = {
    "小区名称": "世纪村2栋3座05B",
    "标题": "深圳市南山区沙河街道世纪村2栋3座05B房产",
    "区域": "深圳市",
    "坐落": "深圳市南山区沙河街道世纪村2栋3座05B房产",
    "建筑面积": "153.34",
    "户型": "三室一厅",
    "朝向": "南",
    "所在楼层": "5",
    "总层数": "18",
    "装修": "简装",
    "房龄": "10",
    "房屋用途": "住宅",
    "建筑结构": "钢混",
    "起拍价": "697.94",
    "参考价": "872.43",
    "参考价类型": "评估价",
    "折扣率": "8.0",
    "单价": "4.55",
    "省额": "174.49",
    "保证金": "100",
    "增价幅度": "1",
    "开拍时间": "2026-09-01 10:00",
    "腾空交付": "无",
    "权利限制": "法院查封",
    "税费": "各付各税",
    "周边配套": "商圈成熟",
    "最近地铁距离": "712",
    "最近医院距离": "978",
}


def test_all_angles_filled_and_no_placeholder_left():
    """契约: 8 个角度齐全, 输出不含未填占位符, 无连续标点。"""
    filled = fill_templates(BASE_FIELDS, seed="test1")
    assert set(filled) == set(ANGLE_ORDER)
    for text in filled.values():
        assert not re.search(r"\{[\u4e00-\u9fff\w]+\}", text), f"残留占位符: {text}"
        assert not re.search(r"[，。；！？、：]{2,}", text), f"连续标点: {text}"


def test_partial_fill_removes_whole_segment():
    """契约: 缺失字段所在整段(按标点切段)被删除, 不留"最近医院米"式残句。"""
    fields = dict(BASE_FIELDS)
    fields["最近医院距离"] = ""
    filled = fill_templates(fields, seed="t2")
    dd = filled["地段与配套"]
    assert not re.search(r"\{[\u4e00-\u9fff\w]+\}", dd)


def test_no_discount_rows_skipped():
    """契约: 起拍=评估价(无折扣)时, 不出"10折/立省0万"。"""
    fields = dict(BASE_FIELDS)
    fields["起拍价"] = "872.43"
    fields["折扣率"] = "10.0"
    fields["省额"] = "0.00"
    filled = fill_templates(fields, seed="t3")
    blob = "".join(filled.values())
    assert "10.0折" not in blob and "10折" not in blob and "立省0.00万" not in blob


def test_seed_determinism():
    """契约: 同一 seed 输出一致。"""
    assert fill_templates(BASE_FIELDS, seed="abc") == fill_templates(BASE_FIELDS, seed="abc")


def test_relax_needs_at_least_half_fields():
    """契约: 少于一半占位符可填的行不采用(回退到固定行或全填行)。"""
    fields = dict(BASE_FIELDS)
    for k in ("户型", "朝向", "所在楼层", "总层数"):
        fields[k] = ""
    filled = fill_templates(fields, seed="t4")
    assert set(filled) == set(ANGLE_ORDER)


def test_clean_text_trailing_comma():
    """契约: _clean_text 去掉句尾逗号族, 保留句末！？。"""
    assert _clean_text("108㎡，朝南采光，") == "108㎡，朝南采光"
    assert _clean_text("手慢无。") == "手慢无。"
    assert _clean_text("最近医院米、") == "最近医院米"


def test_extract_fields_area_sanity():
    """契约: 建筑面积优先取「合计」; 超 100 万㎡ 垃圾值置空; 单价 <0.005 置空。"""
    data = {
        "start_price": 1720000,
        "ref_price": 2000000,
        "ref_price_type": "评估价",
        "property_info": {
            "建筑面积": "150921.40平方米",
            "建筑面积_合计": "208.59",
        },
    }
    f = extract_fields(data, "测试房产一处")
    assert f["建筑面积"] == "208.59", f"应取合计: {f['建筑面积']}"

    data2 = {
        "start_price": 1720000,
        "ref_price": 2000000,
        "property_info": {"建筑面积": "207150921.40平方米"},
    }
    f2 = extract_fields(data2, "测试房产一处")
    assert f2["建筑面积"] == "", f"超大面积应置空: {f2['建筑面积']}"
    assert f2["单价"] == "", f"单价应置空: {f2['单价']}"


def test_build_full_script_order():
    """契约: 完整话术按 ANGLE_ORDER 顺序拼接, 且可被解析回同样 dict。"""
    filled = fill_templates(BASE_FIELDS, seed="t5")
    script = build_full_script(filled)
    assert script.startswith("【开场钩子】")
    assert script.rstrip().endswith(f"【行动号召】{filled['行动号召']}")
    angles = re.findall(r"【(.+?)】", script)
    assert angles == [a for a in ANGLE_ORDER if a in filled]


# ─── LLM 增强校验(不调 API) ───

_spec2 = importlib.util.spec_from_file_location(
    "llm_enhance", PROJ / "skills/script-writer/scripts/llm_enhance.py")
le = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(le)


def _rule():
    return {
        "开场钩子": "世纪村2栋3座05B一套153.34㎡法拍房，起拍仅697.94万，捡漏窗口开了！",
        "房源硬指标": "房源性价比看硬指标，面积、户型、楼层、装修，这几项达标才值得冲。",
        "价格解析": "评估价872.43万，起拍697.94万，直接8.0折，折算单价才4.55万/㎡。",
        "地段与配套": "坐落：深圳市南山区沙河街道世纪村2栋3座05B房产，核心地段，配套成熟。",
        "常见误区": "误区“必须全款”？看付款期限，697.94万这套杠杆用得好压力小。",
        "风险提示": "法拍流程复杂，建议咨询专业助拍，别盲目下手。",
        "紧迫感": "法拍房每轮就一套，看中的别等，等就是留给别人。",
        "行动号召": "关注我，带你了解更多法拍房！",
    }


def test_llm_validate_accepts_faithful_rephrase():
    """契约: 措辞不同但数字一致的润色稿通过校验。"""
    ok = dict(_rule())
    ok["价格解析"] = "评估价872.43万，起拍697.94万，约合8.0折，折算下来每平4.55万。"
    ok["行动号召"] = "点个关注，法拍房知识天天见！"
    assert le.validate(_rule(), BASE_FIELDS, ok)


def test_llm_validate_rejects_invented_number():
    """契约: 出现事实里没有的数字(幻觉) → 校验不通过。"""
    bad = dict(_rule())
    bad["价格解析"] = "评估价872.43万，起拍697.94万，立省500万，捡大漏。"  # 500 不在事实里
    assert not le.validate(_rule(), BASE_FIELDS, bad)


def test_llm_validate_rejects_missing_angle():
    """契约: 角度缺失/多余 → 校验不通过。"""
    missing = dict(_rule())
    missing.pop("行动号召")
    assert not le.validate(_rule(), BASE_FIELDS, missing)
    extra = dict(_rule())
    extra["新角度"] = "多了一个"
    assert not le.validate(_rule(), BASE_FIELDS, extra)


def test_llm_prompt_contains_notes():
    """契约: prompt 里带「子主题/备注」(使用限制)给 LLM 看。"""
    _, user = le.build_prompt(_rule(), BASE_FIELDS)
    assert "子主题" in user
    assert "备注" in user


# ─── 源准入(备注「仅 ali」行) ───

def _ali_row(subtopic):
    return {"子主题": subtopic, "备注": "仅 ali 源，测试用"}


def test_ali_only_rows_gated_by_source():
    """契约: 备注含「仅 ali」的行, gpai/未知源不可选; ali 且有 POI 才可选。"""
    fields = dict(BASE_FIELDS)
    allowed = gs._row_allowed
    assert allowed(_ali_row("实测配套"), "gpai", fields) is False
    assert allowed(_ali_row("实测配套"), "", fields) is False
    assert allowed(_ali_row("实测配套"), "ali", fields) is True

    nopoi = dict(fields)
    for k in ("最近地铁距离", "最近学校距离", "最近商场距离", "最近医院距离", "最近公园距离"):
        nopoi[k] = ""
    assert allowed(_ali_row("实测配套"), "ali", nopoi) is False
    # 非 ali 专属行不受影响
    assert allowed({"子主题": "坐落", "备注": ""}, "gpai", nopoi) is True


def test_gpai_never_gets_ali_fixed_row():
    """契约(端到端): gpai 源的话术绝不出现「阿里源实测」固定行。"""
    fields = dict(BASE_FIELDS)
    for seed in ("g1", "g2", "g3", "g4", "g5"):
        filled = fill_templates(fields, seed=seed, source="gpai")
        assert "阿里源实测" not in filled.get("地段与配套", ""), f"seed={seed}"


def _walk_row():
    return {"子主题": "实测配套",
            "备注": "仅 ali 源且步行范围(需 地铁/学校/医院/公园 距离全部存在且≤1200米)"}


def _walk_fields(overrides=None):
    f = {"最近地铁距离": "712", "最近学校距离": "1000", "最近医院距离": "978", "最近公园距离": "306"}
    if overrides:
        f.update(overrides)
    return f


def test_walking_range_gate():
    """契约: 「步行范围内」宣称仅在 地铁/学校/医院/公园 距离全部存在且≤1200米 时放行。"""
    assert gs._row_allowed(_walk_row(), "ali", _walk_fields()) is True
    assert gs._row_allowed(_walk_row(), "ali", _walk_fields({"最近医院距离": "2400"})) is False
    assert gs._row_allowed(_walk_row(), "ali", _walk_fields({"最近学校距离": ""})) is False
    assert gs._row_allowed(_walk_row(), "gpai", _walk_fields()) is False
    assert gs._row_allowed(_walk_row(), "", _walk_fields()) is False


def test_walking_claim_only_when_within_range():
    """契约(端到端): 医院 2400 米时绝不出现"均在步行范围内"。"""
    far = dict(BASE_FIELDS)
    far["最近地铁距离"] = "712"
    far["最近学校距离"] = "800"
    far["最近医院距离"] = "2400"
    far["最近公园距离"] = "306"
    for seed in ("w1", "w2", "w3", "w4", "w5"):
        filled = fill_templates(far, seed=seed, source="ali")
        assert "均在步行范围内" not in filled.get("地段与配套", ""), f"seed={seed}"
