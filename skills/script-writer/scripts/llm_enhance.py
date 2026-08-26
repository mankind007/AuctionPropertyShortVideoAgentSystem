"""话术 LLM 增强(可选): 把规则稿交给通义千问润色, 严格"改措辞不改事实"。

- 输入: 规则话术 {角度: 文案} + 房源事实字段 + 话术素材库(含「备注」使用限制)
- 输出: 校验通过的润色稿 {角度: 文案}; 任一校验不过或 API 失败 → 返回 None(调用方回退规则稿)
- LLM 基座: agent/model.py(DashScope, OpenAI 兼容)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from agent.model import LLMError, chat

ANGLES = [
    "开场钩子", "房源硬指标", "价格解析", "地段与配套",
    "常见误区", "风险提示", "紧迫感", "行动号召",
]


def _load_templates() -> list[dict]:
    csv_path = Path(__file__).resolve().parents[3] / "assets" / "短视频宣传话术.csv"
    import csv
    with open(csv_path, encoding="utf-8-sig") as fp:
        return list(csv.DictReader(fp))


def _templates_for_prompt() -> dict:
    """素材库按角度聚合, 只带子主题+备注(给 LLM 看使用限制), 不带模板正文(避免诱导填占位符/爆上下文)。"""
    out: dict = {}
    for t in _load_templates():
        angle = t["角度"]
        out.setdefault(angle, []).append({
            "子主题": t.get("子主题", ""),
            "备注": t.get("备注", ""),
        })
    return out


def _nums(text: str) -> set[float]:
    return {round(float(m), 2) for m in re.findall(r"\d+(?:\.\d+)?", str(text))}


def _allowed_nums(rule: dict, fields: dict) -> set[float]:
    allowed = set()
    for t in rule.values():
        allowed |= _nums(t)
    # 字段值可能是"5层，共18层"这类合并串 → 正则提取全部数字, 不能整体 float
    for v in fields.values():
        allowed |= _nums(v)
    return allowed


def _find_issue(rule: dict, fields: dict, parsed: dict) -> Optional[str]:
    """返回首个违规原因(无则 None)。含角度齐全/占位符/标点/数字不越界。"""
    if not isinstance(parsed, dict):
        return "解析结果非 JSON 对象"
    if set(parsed.keys()) != set(rule.keys()):
        missing = set(rule) - set(parsed)
        extra = set(parsed) - set(rule)
        return f"角度不齐 缺={missing} 多={extra}"
    allowed = _allowed_nums(rule, fields)
    for angle, text in parsed.items():
        t = str(text or "").strip()
        if not t:
            return f"[{angle}] 文案为空"
        if re.search(r"\{[\u4e00-\u9fff\w]+\}", t):
            return f"[{angle}] 残留占位符: {t}"
        if re.search(r"[，。；！？]{2,}", t):
            return f"[{angle}] 连续标点: {t}"
        if "10.0折" in t or "10折" in t:
            return f"[{angle}] 出现10折: {t}"
        if re.search(r"立省-?0(\.0*)?万", t):
            return f"[{angle}] 立省0: {t}"
        bad = _nums(t) - allowed
        if bad:
            return f"[{angle}] 编造数字 {sorted(bad)} (不在事实/规则稿中): {t}"
    return None


def validate(rule: dict, fields: dict, parsed: dict) -> bool:
    """校验 LLM 稿: 角度齐全/无占位符/无连续标点/数字不越界(无编造)。"""
    return _find_issue(rule, fields, parsed) is None


def build_prompt(rule: dict, fields: dict, nudge: str = "") -> tuple[str, str]:
    fact = {k: v for k, v in fields.items() if str(v).strip()}
    system = (
        "你是法拍房短视频口播稿润色专家。你会收到: (1)该房源的【事实字段】;"
        "(2)已由规则生成、数字准确的【规则稿】;"
        "(3)话术素材库按角度的【子主题/备注】(备注=使用限制)。"
        "你的任务: 在不改变任何事实数字含义的前提下, 把规则稿润色得更口语化、更有钩子、更自然,"
        "并严格遵守素材库备注里的使用限制。硬性要求:\n"
        "1. 只输出 JSON 对象, 键固定为 8 个角度(一个不能少、不能多、不要截断): "
        "开场钩子 / 房源硬指标 / 价格解析 / 地段与配套 / 常见误区 / 风险提示 / 紧迫感 / 行动号召\n"
        "2. 每个角度一句话, 口语化、有吸引力, 8 句句式不要雷同\n"
        "3. 所有数字必须逐字来自【事实字段】中的原值: 价格/面积/距离/折扣/楼层/开拍时间等, "
        "不得改写、换算、四舍五入或新增任何数字; 事实字段缺失时绝不编造\n"
        "4. 不得出现形如 {xxx} 的占位符\n"
        "5. 不编造不存在的信息(如没有的配套/医院/地铁/楼层)\n"
        "6. 不要写联系/咨询/电话等内容(系统另行标注)"
    )
    user = (
        "事实字段:\n" + json.dumps(fact, ensure_ascii=False, indent=1) +
        "\n\n规则稿:\n" + json.dumps(rule, ensure_ascii=False, indent=1) +
        "\n\n话术素材库备注(角度 → 子主题/备注, 备注=使用限制):\n" +
        json.dumps(_templates_for_prompt(), ensure_ascii=False, indent=1) +
        (("\n\n" + nudge) if nudge else "") +
        "\n\n只输出 JSON。"
    )
    return system, user


def _parse_reply(reply: str) -> Optional[dict]:
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", reply, re.S)
    if m:
        reply = m.group(1)
    try:
        return json.loads(reply)
    except json.JSONDecodeError:
        return None


def enhance(rule: dict[str, str], fields: dict[str, str], *, source: str = "") -> Optional[dict[str, str]]:
    """润色规则稿; 校验不过或 API 失败返回 None(调用方回退规则稿)。

    模型输出偶发不完整/编造数字 → 语义重试最多 3 次, 每次附失败原因提示。
    """
    nudges = [
        "",
        "上一次输出不完整或含事实外数字。请务必一次性输出【全部 8 个角度】, "
        "且每个数字都必须是【事实字段】里出现过的原值, 不要改写、换算或新增。",
        "再次提醒: 逐字核对 8 个角度齐全, 数字只允许来自事实字段, 否则视为无效。",
    ]
    for attempt in range(3):
        try:
            system, user = build_prompt(rule, fields, nudge=nudges[attempt])
            reply = chat(system, user, json_mode=True)
            parsed = _parse_reply(reply)
            issue = _find_issue(rule, fields, parsed) if parsed else "解析失败"
            if issue is None:
                return {a: parsed[a] for a in ANGLES if a in parsed}
            print(f"  [LLM] {source} 第{attempt + 1}次失败 — {issue}")
            if attempt < 2:
                print(f"  [LLM]   reply 前200字: {str(reply)[:200]}")
        except LLMError as exc:
            print(f"  [LLM] {source} 第{attempt + 1}次调用失败: {exc}")
            if attempt >= 2:
                return None
    return None
