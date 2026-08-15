"""跨技能共享的文本/URL 解析工具(带类型注解)。

公拍网(gpai)与阿里资产(ali)两个爬虫复用的纯函数,集中于此避免重复。
用法: `from utils.parsing import to_int_price, extract_time, item_url, now_iso`
"""
from __future__ import annotations

import datetime
import re
from typing import Optional


def now_iso() -> str:
    """当前本地时间 ISO 格式(不含微秒),作为采集时间戳。"""
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def to_int_price(text: Optional[str]) -> Optional[float]:
    """把价格文本转成元。容忍开头的 ￥/¥、千分位逗号与任意中文单位组合。

    支持 百元/千元/万元/十万元/百万元/千万元/亿元/十亿元 等中文单位。
    无法解析时返回 None。
    """
    if not text:
        return None
    t = text.strip().lstrip("￥¥").strip()
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*([十百千万亿]*元?)?", t)
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    unit = (m.group(2) or "元").strip()
    mult = 1.0
    if unit:
        if "亿" in unit:
            mult *= 1e8
        if "万" in unit:
            mult *= 1e4
        if "千" in unit:
            mult *= 1e3
        if "百" in unit:
            mult *= 100
        if "十" in unit:
            mult *= 10
    return round(num * mult, 2)


def extract_time(text: Optional[str]) -> Optional[str]:
    """从文本中提取形如 '开始时间:2026-8-13 10:00:00' 的原始时间串。

    仅提取时间串本身,不区分开始/结束;区分由调用方按行标签处理。
    """
    if not text:
        return None
    t = text.strip()
    m = re.search(r"(\d{4}[-/]\d{1,2}[-/]\d{1,2}\s*\d{1,2}:\d{2}(?::\d{2})?)", t)
    return m.group(1) if m else None


def item_url(fragment: Optional[str]) -> str:
    """链接片段补全为完整 URL('' → '';http 前缀原样;否则加 https:)。"""
    if not fragment:
        return ""
    if fragment.startswith("http"):
        return fragment
    return "https:" + fragment


def row_label(text: str) -> str:
    """从数据行文本提取前导标签('评估价：1,056,669元' → '评估价')。"""
    m = re.match(r"^\s*([^：:]+)[：:]", text)
    return m.group(1).strip() if m else ""