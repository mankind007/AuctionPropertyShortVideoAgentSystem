"""标的物描述/属性提取。

描述(ali/gpai):
- 新规则(需求.txt): 描述是包含「拍卖标的…」标记的「第N条」小节, 取该节起到下一节「第N+1条」前,
  换行替换为空格并去掉首尾空格;
- 旧规则兜底(docs/初步信息): 未用「第N条」分节的公告, 取「拍卖标的…」到最近章节标题「X、」之间;
- 无法按要求分段(无标记/结果过短)回退整段原文, 防丢数据。

公拍网标的物介绍表格(gpai property_info):
- 支持「调查情况表/审批表」里三种形态并拍扁为扁平 dict:
  两列 label/value(值可 colspan)、rowspan 分组(如 拍品现状|用途|办公用房)、多列多行(如 权证表, 行首标识做前缀)。
- 面积取值优先级: 结构化表内「建筑总面积/建筑面积」→ 公告段落(埋段回退)→ 标的物介绍段落。
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

from utils.parsing import to_int_price

_MARKER = re.compile(r"拍卖标的(?:物)?[:：]")
_SECTION = re.compile(r"第\s*[\d一二三四五六七八九十百零两]+\s*条")
_HEADER = re.compile(r"(?:[一二三四五六七八九十]+)、")
# 「标的物属性」区块后的下一个主要区块标题(截断边界)
_PROP_BOUNDARY = re.compile(
    r"标的物详情描述|竞买人条件|拍卖流程|拍卖程序|"
    r"第\s*[\d一二三四五六七八九十百零两]+\s*条|"
    r"[一二三四五六七八九十]+、"
)


def extract_property_info(raw: str | None) -> dict:
    """提取「标的物属性」为结构化 dict({属性名: 值}), 无该区块返回 {}。

    从「标的物属性」标签起, 到下一个主要区块标题(标的物详情描述/竞买人条件/第N条/X、)为止;
    属性行形如 `段落名：` + 值(可能同行或续行), 值内换行折叠为空格。
    """
    if not raw:
        return {}
    raw = raw.strip()
    i = raw.find("标的物属性")
    if i < 0:
        return {}
    seg = raw[i:]
    m = _PROP_BOUNDARY.search(seg)
    if m and m.start() > 0:
        seg = seg[: m.start()]
    return _parse_pairs(seg)


def _parse_pairs(block: str) -> dict:
    """把 `键：值`(键可能独占一行、值可续行)解析为 dict。"""
    pairs: dict[str, str] = {}
    cur_key = None
    cur_val: list[str] = []
    for ln in block.splitlines():
        s = ln.strip()
        if not s:
            continue
        m = re.match(r"^(.+?)[：:]\s*$", s)
        if m:
            if cur_key and cur_val:
                pairs[cur_key] = _normalize_value(" ".join(cur_val))
            cur_key = m.group(1).strip()
            cur_val = []
            continue
        m2 = re.match(r"^(.+?)[：:]\s*(.+)$", s)
        if m2:
            if cur_key and cur_val:
                pairs[cur_key] = _normalize_value(" ".join(cur_val))
            cur_key = m2.group(1).strip()
            cur_val = [m2.group(2).strip()]
            continue
        if cur_key:
            cur_val.append(s)
    if cur_key and cur_val:
        pairs[cur_key] = _normalize_value(" ".join(cur_val))
    return pairs


def extract_auction_description(raw: str | None) -> str:
    if not raw:
        return ""
    raw = raw.strip()
    m = _MARKER.search(raw)
    if not m:
        return raw
    secs = list(_SECTION.finditer(raw))
    start = None
    for h in secs:
        if h.start() <= m.start():
            start = h.start()
        else:
            break
    if start is None:
        return _old_rule(raw, m)
    end = next((h.start() for h in secs if h.start() > start), None)
    seg = raw[start:] if end is None else raw[start:end]
    seg = _normalize_value(seg)
    return seg if len(seg) >= 6 else raw


def _old_rule(raw: str, m: re.Match) -> str:
    seg = raw[m.end():]
    cut = _HEADER.search(seg)
    if cut:
        seg = seg[: cut.start()]
    seg = _normalize_value(seg)
    return seg if len(seg) >= 6 else raw.strip()


# ---------------------------------------------------------------------------
# 公拍网标的物介绍表格拍扁(gpai property_info)
# ---------------------------------------------------------------------------
_AREA_KEY_RE = re.compile(r"建筑总面积|建筑面积|房屋建筑面积|套内面积|总面积")
_AREA_VALUE_RE = re.compile(
    r"(建筑总面积|建筑面积|房屋建筑面积|套内面积|总面积|面积)[：: ]{0,3}"
    r"(\d+(?:\.\d+)?)\s*(平方米|㎡|m²|m2)?"
)


class _GpaiTableParser(HTMLParser):
    """解析 HTML 表格为 cell 网格(含 rowspan/colspan 信息), 供拍扁使用。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.grids: list[list[list[dict]]] = []
        self._table: list[list[dict]] | None = None
        self._row: list[dict] | None = None
        self._cell: dict | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = {
                "text": "",
                "colspan": int(a.get("colspan", 1) or 1),
                "rowspan": int(a.get("rowspan", 1) or 1),
            }

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["text"] += data

    def handle_endtag(self, tag):
        if tag in ("td", "th"):
            if self._cell is not None and self._row is not None:
                self._row.append(self._cell)
            self._cell = None
        elif tag == "tr":
            if self._row is not None and self._table is not None:
                self._table.append(self._row)
            self._row = None
        elif tag == "table":
            if self._table is not None:
                self.grids.append(self._table)
            self._table = None


def _expand_gpai_grid(table: list[list[dict]]) -> list[list[dict | None]]:
    """把带 rowspan/colspan 的 table 展开为 `grid[r][c] = cell|None` 满网格。

    跨行延续位置打 `_cont=True` 标记(用于识别 rowspan 组名列)。
    """
    ncols = 0
    for row in table:
        ncols = max(ncols, sum(c["colspan"] for c in row))
    grid: list[list[dict | None]] = []
    rowspan_pending: dict[int, tuple[dict, int]] = {}
    for row in table:
        cells: list[dict | None] = [None] * ncols
        for col, (cell, remain) in list(rowspan_pending.items()):
            cells[col] = dict(cell)
            cells[col]["_cont"] = True
            if remain <= 1:
                del rowspan_pending[col]
            else:
                rowspan_pending[col] = (cell, remain - 1)
        c = 0
        for cell in row:
            while c < ncols and cells[c] is not None:
                c += 1
            cs, rs = cell["colspan"], cell["rowspan"]
            fresh = dict(cell)
            fresh["_cont"] = False
            for cc in range(c, min(c + cs, ncols)):
                cells[cc] = fresh
            if rs > 1:
                rowspan_pending[c] = (cell, rs - 1)
            c += cs
        grid.append(cells)
    return grid


def _gpai_cell_text(cell: dict | None) -> str:
    if not cell:
        return ""
    return " ".join(cell["text"].split()).strip()


def _gpai_row_cells(row: list[dict | None]) -> list[tuple[str, int, dict]]:
    """一行中连续的、去重后的 (文本, 起始列, cell) 列表(colspan 展开的相邻重复合并)。"""
    out: list[tuple[str, int, dict]] = []
    prev = None
    for col, cell in enumerate(row):
        if cell is None:
            prev = None
            continue
        t = _gpai_cell_text(cell)
        if not t:
            prev = None
            continue
        if prev is not None and t == _gpai_cell_text(prev):
            continue
        out.append((t, col, cell))
        prev = cell
    return out


def _flatten_gpai_table(html: str) -> dict[str, str]:
    """把公拍网标的物介绍表格拍扁为扁平 dict。

    支持三种形态(见测试):
    - 两列 label/value(值列可 colspan)
    - rowspan 分组: 组名列(第 0 列跨多行)丢弃, 保留 子键/值(如 拍品现状|用途|办公用房);
      仅组名+单值(无子键)时保留 {组名: 值}
    - 多列多行(如 53063 权证表): 行首标识列做前缀键 `幢号和部位_779弄53号301室_建筑面积`,
      多套房产互不覆盖
    """
    parser = _GpaiTableParser()
    parser.feed(html or "")
    out: dict[str, str] = {}
    for table in parser.grids:
        grid = _expand_gpai_grid(table)
        if not grid:
            continue

        def is_group_col(cell: dict | None) -> bool:
            return bool(cell) and (cell.get("_cont") or int(cell.get("rowspan", 1) or 1) > 1)

        # 识别「多列多行」表头: 首行 ≥3 个非空 cell、首格非组名列、与下一行同宽
        header_idx = None
        for r in range(len(grid) - 1):
            cells = _gpai_row_cells(grid[r])
            if len(cells) < 3 or is_group_col(cells[0][2]):
                continue
            nxt = _gpai_row_cells(grid[r + 1])
            if len(nxt) >= 3:
                header_idx = r
                break
        if header_idx is not None:
            headers = [(t, s) for t, s, _ in _gpai_row_cells(grid[header_idx])]
            id_start = headers[0][1]
            for t, s in headers:
                if any(k in t for k in ("幢号", "部位", "名称", "标的", "座", "室")):
                    id_start = s
                    break
            for row in grid[header_idx + 1:]:
                dcells = _gpai_row_cells(row)
                if len(dcells) < 2:
                    continue
                by_start = {s: t for t, s, _ in dcells}
                id_val = by_start.get(id_start) or (dcells[0][0] if dcells else "")
                if not id_val:
                    continue
                for h, s in headers:
                    if s == id_start:
                        continue
                    v = by_start.get(s)
                    if v:
                        out[f"{h}_{id_val}"] = v
        else:
            # 两列 / rowspan 分组
            for row in grid:
                cells = _gpai_row_cells(row)
                if len(cells) < 2:
                    continue
                first_cell = cells[0][2]
                if is_group_col(first_cell):
                    rest = cells[1:]
                    if len(rest) >= 2:
                        out[rest[0][0]] = rest[-1][0]
                    elif rest and not first_cell.get("_cont"):
                        # 组名+单值(无子键), 如 权利限制情况|被查封
                        out[cells[0][0]] = rest[0][0]
                else:
                    out[cells[0][0]] = cells[-1][0]
    return out


def extract_gpai_property_info(intro_html: str | None, announce_text: str | None,
                               intro_text: str | None = None) -> dict:
    """从公拍网标的物介绍表格提取扁平 property_info; 面积按优先级解析。

    优先级: 结构化表内「建筑总面积/建筑面积…」→ 公告段落(埋段回退)→ 标的物介绍段落。
    无任何可解析数据返回 {}。
    """
    out = _flatten_gpai_table(intro_html or "")
    area = None
    for k in ("建筑总面积", "建筑面积", "房屋建筑面积", "套内面积", "总面积"):
        if k in out and _AREA_VALUE_RE.search(out[k]):
            area = (k, out[k])
            break
    if area is None:
        for src in (announce_text, intro_text):
            if not src:
                continue
            m = _AREA_VALUE_RE.search(src)
            if m:
                area = ("建筑面积", f"{m.group(2)}{m.group(3) or ''}")
                break
    if area is not None:
        out[area[0]] = area[1]
    return out


# ---------------------------------------------------------------------------
# description 纯文本 → 结构化字段提取
# ---------------------------------------------------------------------------
_DESC_FIELD_PATTERNS: dict[str, re.Pattern[str]] = {
    "房产地址": re.compile(
        r"(?:拍卖标的[物]?|位于|本次拍卖(?:对象|标的)为?)[：: ]?\s*([^（(。；;，,\n]+)"
        r"|^(?!第\s*[\d一二三四五六七八九十百零两]+\s*条)(?!标的物属性)(?!.*拍卖标的)"
        r"([^（(。；;，,\n]{6,40})"
    ),
    "建筑面积": re.compile(
        r"(?:建筑面积|建筑总面积|房屋建筑面积|房屋面积|套内面积|总面积|房产面积|面积)[为是]?[:：]?\s*"
        r"(\d+(?:\.\d+)?)\s*(平方米|㎡|m²|m2|平方|平)"
    ),
    # 所在层/总楼层：1-5/5 → 所在层=1-5, 总层=5
    "总层数": re.compile(
        r"(?:所在层/|所在楼层/)?总(?:楼层|层数)[为是]?[:：]?\s*(\d+)\s*层?"
        r"|所在层/总楼层[：:]\s*\d+(?:-\d+)?\s*/\s*(\d+)"
        r"|全部楼层[为是]?[:：]?\s*(\d+)\s*层?"
    ),
    "所在层数": re.compile(
        r"(?:所在层数|所在楼层|所在层)[为是]?[:：]?\s*(\d+(?:-\d+)?)\s*层?"
        r"|所在层/总楼层[：:]\s*(\d+(?:-\d+)?)\s*/\s*\d+"
    ),
    "朝向": re.compile(r"朝向[为是]?[:：]?\s*([^，,。;；\s]+)"),
    "不动产权证号": re.compile(
        r"(?:不动产权证|不动产权证书|房地产权证|不动产权|产权证|权证|产籍号|证书字号|权利证书)[号为]?[：:]?\s*"
        r"([^，,。;；\]\s]*?号(?:[（(]原[：:][^）)]{0,20}[）)])?|"
        r"[^，,。;；\]（()\s]{2,16}(?![\u4e00-\u9fff\d]))"
    ),
    "房屋类型": re.compile(
        r"(?:物业类型|房屋类型|规划用途|设计用途|房屋用途|用途)[为]?[:：]?\s*([^，,。;；\s]+)"
    ),
    "配套设施": re.compile(r"配套[:：]?\s*([^，。]+)"),
    "房屋现状": re.compile(r"房屋现状[:：]?\s*([^，。]+)"),
    "房屋结构": re.compile(r"房屋结构[为]?[:：]?\s*([^，,。;；\s]+)"),
    "保证金": re.compile(r"保证金[为]?[:：]?\s*([￥¥]?[\d，, ]+(?:\.\d+)?\s*[万亿千百十]*元?)"),
    "增价幅度": re.compile(
        r"(?:增价幅度|加价幅度|增幅)[为]?[:：]?\s*([￥¥]?[\d，, ]+(?:\.\d+)?\s*[万亿千百十]*元?)"
    ),
    "抵押信息": re.compile(
        r"(?:抵押信息|权利限制)[为]?[:：]?\s*([^，,。;；\s]+)"
        r"|(有|无|存在)\s*(?:抵押|抵押权人|查封)"
    ),
    "优先购买权": re.compile(r"(有|无)\s*优先购买权人"),
    "租赁情况": re.compile(
        r"(?:租赁情况|租赁|出租)[为]?[:：]?\s*([^，,。;；\s]+)"
        r"|(有|无)\s*(?:租赁|出租)"
    ),
    "装修情况": re.compile(r"(?:装修情况|装修)[为]?[:：]?\s*([^，,。;；\s]+)"),
    "土地使用年限": re.compile(
        r"(?:土地使用年限|使用年限|出让年限|产权(?:年限|为))[为是]?[:：]?\s*(\d+)\s*年"
    ),
    "户型": re.compile(
        r"户型[为]?[:：]?\s*([^，,。;；\s]+)"
        r"|([一二三四五六七八九十两\d]+室[一二三四五六七八九十两\d]+厅(?:[一二三四五六七八九十两\d]+卫)?)"
    ),
    "土地用途": re.compile(r"土地用途[为]?[:：]?\s*([^，,。;；\s]+)"),
}

# 价格类字段: 统一转元数值;其余字段保留字符串原文
_PRICE_FIELDS = frozenset({"保证金", "增价幅度"})

# 行政区划解析: 省/自治区/直辖市/市/自治州/县/区/旗/新区
_REGION_RE = re.compile(
    r"([\u4e00-\u9fff]+?(?:省|自治区|直辖市|特别行政区|自治州|市|自治县|县|市辖区|旗|区|新区))"
)
# 前缀污染: 区域匹配串中常见的非区域介词/动词, 命中后截断取其尾
_POLLUTION_WORDS = ("根据", "接联系", "已", "被", "标的", "位于", "坐落于", "本次",
                    "对象为", "拍卖", "依职权", "公开", "法院", "卖", "对象", "标的物",
                    "市辖区", "为本市", "在本市", "本市", "在", "向", "到", "始前", "一同",
                    "小商品", "批发", "需要", "承担", "缴费", "致电")
# 直接排除的匹配串(含这些词的整串视为非区域)
_BLACKLIST = ("房权证", "权证", "上市", "国用", "地产", "需要", "承担", "缴费", "小商品")
# 排除"号北区/栋X区/楼西区"等非行政区划的误判: 区/县前一个字符为号/栋/楼/院/小区/路/街/弄
_BAD_PREFIX = re.compile(r"[号栋楼院]|小区|路|街|弄")
_REGION_SUFFIX = ("省", "自治区", "直辖市", "特别行政区", "自治州", "市",
                  "自治县", "县", "市辖区", "旗", "新区")


def extract_region(raw: str) -> list[str]:
    """从文本中解析行政区划层级(省→市→县区),返回按出现顺序去重的列表。"""
    if not raw:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for m in _REGION_RE.finditer(raw):
        r = m.group(1)
        if r in seen or r in out:
            continue
        # 区域名一般 2-5 字; 超长多为"前缀污染"(惰性匹配吞并前文)
        if len(r) > 6:
            # 从尾部取最近一个区域名(前缀污染时真实区域在串尾)
            tail = re.search(
                r"([\u4e00-\u9fff]{2,5}(?:省|自治区|直辖市|特别行政区|自治州|市|自治县|县|市辖区|旗|区|新区))$",
                r,
            )
            r = tail.group(1) if tail else ""
        # 截掉污染前缀(动词/介词/法院名等), 保留尾部真实区域名
        for w in _POLLUTION_WORDS:
            i = r.find(w)
            if i >= 0:
                r = r[i + len(w):]
        if not r or len(r) > 6:
            continue
        # 直接排除黑名单词
        if any(w in r for w in _BLACKLIST):
            continue
        # 排除"号北区/栋X区/小区南区/东方红街"等非行政区划误判
        if r.endswith("小区") or _BAD_PREFIX.search(r[:-1]):
            continue
        if r in seen or r in out:
            continue
        seen.add(r)
        out.append(r)
    return out


def _extract_cert_no(ctx: str) -> str | None:
    """从证号上下文(含前缀/后缀)中提取干净的证号, 无效返回 None。

    上下文形如: "证书号：苏（2023）启东市不动产权证明单第0007174号；登记时间" /
    "房地产权证号：宝2013029475（原：宝2001010911）" /
    "权证号为广饶20121099）房产一处"。
    策略: 先剥离关键词前缀, 再匹配标准证号(以 号 结尾)或纯编码, 保留 (原:...) 后缀。
    """
    # 去掉关键词前缀(长词在前, 避免误吃后缀; 含"为/号/字"等衔接)
    stripped = re.sub(r"^(?:.*?)(?:不动产权证书|不动产权证|不动产权|房地产权证|权利证书|"
                      r"证书字号|证书号|产权证|房权证|产籍号|权证)[字号为]{0,3}[：:]?",
                      "", ctx.strip())
    # 丢弃首个顿号/逗号/分号后的内容(多证号取第一个)
    s = re.split(r"[、，,；;]", stripped, maxsplit=1)[0].strip()
    # 去掉前导/尾部干扰符号
    s = s.lstrip("【[{(").rstrip("】]})").strip()
    # 若剥离后以 "第X号" 开头, 但 ctx 在关键词前有 [汉字]（年份）[汉字] 地名前缀,
    # 则把该前缀拼回(如 "（冀（2019）张家口市不动产权第0012640号）" 丢失前缀的场景)
    if re.match(r"^第\d", s):
        m_prev = re.search(
            r"([\u4e00-\u9fff]{1,8}[（(]\s*\d{4}\s*[）)][\u4e00-\u9fff]{0,12}?不动产权(?:证书|证)?)",
            ctx,
        )
        if m_prev:
            s = m_prev.group(1) + s
    if not s:
        return None
    # 标准证号: [地名前缀]?（年份）?[地名]?(关键字)?[第]N号, 以 号 结尾(可带字母)
    m = re.match(
        r"([\u4e00-\u9fff]{0,12}?[（(]?\s*\d{4}\s*[）)]?"
        r"[\u4e00-\u9fff]{0,12}?(?:不动产权|房权证|房地产权证|产权证|产籍|证明单)?"
        r"[\u4e00-\u9fff]{0,6}?(?:第|字第)?[\u4e00-\u9fffA-Za-z]{0,4}?\d{4,}"
        r"[\u4e00-\u9fffA-Za-z]*号?)",
        s,
    )
    if m:
        cert = m.group(1).strip()
        # 截到第一个 "号" 为止(去掉 房产一处 等杂质)
        end = cert.find("号")
        if end >= 0:
            cert = cert[:end + 1]
    else:
        # 宽松兜底: [汉字/字母]? 第X号 / 字第X号 等以 号 结尾
        m = re.match(
            r"([\u4e00-\u9fffA-Za-z]{0,6}?(?:第|字第)?[\u4e00-\u9fffA-Za-z]{0,4}?\d{4,}"
            r"[\u4e00-\u9fffA-Za-z]*号?)",
            s,
        )
        if m:
            cert = m.group(1).strip()
            end = cert.find("号")
            if end >= 0:
                cert = cert[:end + 1]
        else:
            # 纯编码: 汉字+数字 / 大写字母+数字 / 纯数字
            m = re.match(r"([\u4e00-\u9fff]{1,4}\d{4,}[\u4e00-\u9fffA-Za-z]*|"
                         r"[A-Z]{1,2}\d{3,}[\u4e00-\u9fffA-Za-z]*|\d{5,}[\u4e00-\u9fffA-Za-z]*号?)", s)
            cert = m.group(1).strip() if m else None
    if not cert:
        return None
    # 保留可选的 （原:...） 原证号后缀
    if "（原" not in cert:
        tail = re.search(r"[（(]\s*原\s*[：:][^）)]{0,20}[）)]", s[len(cert):])
        if tail:
            cert += tail.group(0)
    # 排除表格表头等非证号词
    if re.search(r"(幢号|部位|面积|类型|用途|坐落|名称|房屋|和|详见|房产一处)", cert):
        return None
    return cert


def is_placeholder_description(desc: str | None) -> bool:
    """描述是否为占位文案(页面 JS 未加载完成时的"公告详情加载中/加载中"等), 判缺共用。"""
    return bool(desc) and ("公告详情" in desc or "加载中" in desc)


def extract_description_fields(description: str | None) -> dict[str, str | float]:
    """从纯文本 description 中提取结构化房产字段(纯正则,不依赖网页)。

    返回扁平 dict: 键=中文字段名,值=字符串(保持原文)或价格类转元数值。
    未命中的字段不出现;description 为空/无任何命中/占位文案返回 {}。
    """
    if not description or is_placeholder_description(description):
        return {}
    raw = " ".join(description.split()).strip()
    out: dict[str, str | float] = {}
    for key, pat in _DESC_FIELD_PATTERNS.items():
        m = pat.search(raw)
        if not m:
            continue
        val = next((g.strip() for g in m.groups() if g and g.strip()), "")
        if not val:
            continue
        if key == "建筑面积":
            unit = m.group(2) or ""
            out[key] = val + unit
        elif key in ("总层数", "所在层数"):
            out[key] = val
        elif key in _PRICE_FIELDS:
            # 清掉数字间的空格(如 "50 000元"),再统一转元
            price = to_int_price(re.sub(r"\s+", "", val) + "元")
            if price is not None:
                out[key] = price
        elif key == "不动产权证号":
            # 取更宽上下文交给 _extract_cert_no 提取完整证号(避免只截到省简称如"云")
            ctx = raw[max(0, m.start() - 25):m.end() + 30]
            cert = _extract_cert_no(ctx)
            if cert is None:
                cert = _extract_cert_no(val)
            if cert is None:
                continue
            out[key] = cert
        else:
            out[key] = val
    regions = extract_region(raw)
    if regions:
        out["所在区域"] = "/".join(regions)
    return out


# ---------------------------------------------------------------------------
# 高价值字段清洗: property_info 统一化 + description 字段提取
# ---------------------------------------------------------------------------
_PROPERTY_KEY_MAP = {
    # 面积(细分键, 各独立: 建筑面积/套内面积/土地面积 不合并)
    "建筑面积": "建筑面积", "建筑面积㎡": "建筑面积", "建筑面积（㎡）": "建筑面积",
    "套内面积": "套内面积", "专有建筑面积": "套内面积",
    "土地面积": "土地面积", "土地使用权面积": "土地面积",
    # 户型
    "房屋户型": "户型", "户型": "户型", "户型情况": "户型", "户型、朝向等情况": "户型",
    # 朝向
    "朝向": "朝向", "房屋朝向": "朝向",
    # 楼层
    "房屋所在楼层": "所在楼层", "所在楼层": "所在楼层", "楼层情况": "所在楼层",
    "总层数": "总层数", "总楼层": "总层数", "层数": "总层数",
    "房屋楼层": "所在楼层", "房产层数": "所在楼层",
    # 建成年份
    "建成时间": "建成年份", "建成年份": "建成年份", "建成年代": "建成年份",
    # 价格(细分键: 起拍价/评估价/变卖价 各自独立)
    "起拍价": "起拍价", "起拍价（万元）": "起拍价", "房产/土地起拍价": "起拍价",
    "评估价": "评估价", "评估价（万元）": "评估价",
    "变卖价": "变卖价",
    "定向询价结果": "起拍价", "网络询价结果": "起拍价",
    "标的物处置参考价": "起拍价", "处置参考价": "起拍价",
    # 产权证号
    "产权证号": "不动产权证号", "不动产权证书号": "不动产权证号",
    "不动产权证号": "不动产权证号", "房屋所有权证": "不动产权证号",
    "房地产权属人": "不动产权证号", "产权证载明建筑面积": "建筑面积",
    "权属证号": "不动产权证号", "权利证号": "不动产权证号",
    "不动产证号": "不动产权证号", "房屋产权证": "不动产权证号",
    # 房屋性质 / 房屋用途(拆分, 不合并)
    "房屋性质": "房屋性质", "性质": "房屋性质", "房屋类型": "房屋性质",
    "用途": "房屋用途", "房屋用途": "房屋用途", "房屋用途及性质": "房屋用途",
    "房屋用途及土地性质": "房屋用途",
    # 建筑结构
    "建筑结构": "房屋结构", "房屋结构": "房屋结构", "结构": "房屋结构",
    # 坐落 / 小区名
    "坐落": "坐落", "标的物名称、坐落位置": "坐落",
    "标的物名称、坐落": "坐落", "房屋四至": "坐落", "拍品名称": "坐落",
    "标的名称": "坐落", "名称": "坐落",
    "小区名称": "小区名称", "不动产名称": "小区名称", "项目名称": "小区名称",
    # 权利人
    "权利人": "权利人", "权属人": "权利人", "所有权人": "权利人",
    "房屋所有权人": "权利人", "拍品所有人": "权利人",
    "权利人及性质": "权利人", "标的所有人": "权利人",
    # 欠费
    "欠费情况": "欠费情况", "物业费": "欠费情况",
    "占有使用或租赁情况": "欠费情况", "租赁情况": "欠费情况",
    # 电梯
    "有无电梯": "电梯", "电梯情况": "电梯",
    # 占用/腾空
    "钥匙": "占用情况", "是否已腾空": "占用情况",
    # 装修
    "装修情况": "装修情况",
    # 税费
    "税费负担": "税费负担", "税费负担方式": "税费负担",
    # 抵押/查封
    "抵押": "抵押", "抵押情况": "抵押",
    "查封": "查封", "查封情况": "查封",
    # 共有/权利来源
    "共有情况": "共有情况",
    "权利来源": "权利来源", "所有权来源": "权利来源",
    # 土地相关(description 常见 `键：值`)
    "土地用途": "土地用途",
    "土地性质": "土地性质", "权利性质": "土地性质",
    "土地使用年限": "土地使用年限", "土地使用期限": "土地使用年限",
    "规划用途": "房屋用途",
    # 房屋结构 / 取得方式
    "房屋结构": "房屋结构",
    "房屋取得方式": "房屋取得方式", "取得方式": "房屋取得方式",
    # 保证金 / 加价幅度
    "保证金": "保证金",
    "加价幅度": "加价幅度", "增价幅度": "加价幅度",
}

def _normalize_key(k: str) -> str:
    """归一化 key: 去除\t\n\r*，连续空格压缩为一个。"""
    k = re.sub(r'[\t\n\r\*]+', ' ', k)
    k = re.sub(r'\s+', ' ', k)
    return k.strip()

_DESCRIPTION_FIELD_PATTERNS = {
    "area": re.compile(r"建筑面积[:：]?\s*(\d+\.?\d*)\s*(平方米|㎡|m²|m2|平米|平方公尺)?", re.I),
    "layout": re.compile(r"([一二三四五六七八九十0-9]+)室([一二三四五六七八九十0-9]+)厅", re.I),
    "orientation": re.compile(r"(?:朝向|朝向)[:：]?\s*([东南西北]+)", re.I),
    "floor": re.compile(r"(?:所在楼层|楼层)[:：]?\s*(\d+)", re.I),
    "total_floors": re.compile(r"总层数[:：]?\s*(\d+)", re.I),
    "build_year": re.compile(r"(?:建成年份|建成年代|建于)[:：]?\s*(\d{4})", re.I),
    "price": re.compile(r"(起拍价|评估价|变卖价)[:：]?\s*[人民币¥]?\s*([\d,]+(?:\.\d+)?)", re.I),
    "property_cert": re.compile(r"(?:产权证号|房产证号|不动产证号)[:：]?\s*([\w]+)", re.I),
}



def _normalize_value(v: str) -> str:
    """归一化 value: \t\n\xa0 换为空格，连续空格压缩为一个，面积单位统一为「平方米」。"""
    if not v:
        return v
    v = re.sub(r'[\t\n\r\xa0]+', ' ', str(v))
    v = re.sub(r' +', ' ', v)
    # 面积单位统一: ㎡/m²/m2/平米/平方公尺 -> 平方米(避免把"平方"误替换成"平方米米")
    v = re.sub(r'(㎡|m²|m2|平米|平方公尺)', '平方米', v)
    return v.strip()


def clean_property_info(info: dict) -> dict:
    """清洗 property_info: 提取高价值字段到 _core。"""
    if not info:
        return {}
    core = {}
    unified_values = set(_PROPERTY_KEY_MAP.values())
    for orig_key, value in info.items():
        if not value:
            continue
        norm_key = _normalize_key(orig_key)
        unified = _PROPERTY_KEY_MAP.get(norm_key)
        if not unified:
            unified = _PROPERTY_KEY_MAP.get(orig_key)
        if not unified and norm_key in unified_values:
            unified = norm_key
        if unified and unified not in core:
            core[unified] = _normalize_value(value)
    return core


# 中文 description 结构化正则的 key -> _core 规范中文键(补充 _PROPERTY_KEY_MAP 未覆盖的)
_DESC_KEY_TO_CORE = {
    "房产地址": "坐落",
    "所在层数": "所在楼层",
    "房屋现状": "占用情况",
    "抵押信息": "抵押",
}


# 英文 description 正则的 key -> _core 规范中文键
_EN_DESC_KEY_TO_CORE = {
    "area": "建筑面积", "layout": "户型", "orientation": "朝向",
    "floor": "所在楼层", "total_floors": "总层数", "build_year": "建成年份",
    "property_cert": "不动产权证号",
}

_PAIR_KEY_RE = re.compile(r"([\u4e00-\u9fffA-Za-z0-9/、（）()]+?)\s*[:：]\s*")


def _extract_desc_pairs(text: str) -> dict[str, str]:
    """扫描 description 中的 `键：值` 干净键值对(支持一行多对), 仅保留可映射到 _core 的键。

    许多阿里公告(description)以 `土地用途：城镇住宅用地`、`保证金：4200元` 等
    冒号分隔的紧凑键值对呈现, 直接按「关键词：`」切片即可高召回提取。
    """
    out: dict[str, str] = {}
    matches = list(_PAIR_KEY_RE.finditer(text))
    for i, m in enumerate(matches):
        key = _normalize_key(m.group(1))
        core_key = _PROPERTY_KEY_MAP.get(key)
        if not core_key:
            continue
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        val = text[start:end].strip()
        val = re.sub(r"[；;，,。\s]+$", "", val).strip(" ；;，,。")
        if not val:
            continue
        if core_key in out:
            continue
        out[core_key] = _normalize_value(val)
    return out


def _extract_from_desc(text: str) -> dict:
    """从 description 文本提取高价值字段(英文正则 + 中文结构化正则, 统一映射到中文 _core)。"""
    if not text:
        return {}
    fields: dict[str, str] = {}
    # 1) 英文正则: area/layout/orientation/floor/total_floors/build_year/price/property_cert
    for key, pattern in _DESCRIPTION_FIELD_PATTERNS.items():
        m = pattern.search(text)
        if not m:
            continue
        if key == "price":
            typ = m.group(1)            # 起拍价 / 评估价 / 变卖价
            val = _normalize_value(m.group(2).strip())
            if val and typ not in fields:
                fields[typ] = val
            continue
        if key == "area":
            unit = m.group(2) or ""
            val = _normalize_value(m.group(1).strip() + unit)
            if val and "建筑面积" not in fields:
                fields["建筑面积"] = val
            continue
        if key == "layout":
            val = _normalize_value(f"{m.group(1)}室{m.group(2)}厅")
            if val and "户型" not in fields:
                fields["户型"] = val
            continue
        val = _normalize_value(m.group(1).strip())
        if not val:
            continue
        if key == "property_cert":
            cert = _extract_cert_no(text[max(0, m.start() - 25):m.end() + 30])
            if cert is None:
                cert = _extract_cert_no(val)
            if cert is None:
                continue
            fields[_EN_DESC_KEY_TO_CORE[key]] = cert
            continue
        core_key = _EN_DESC_KEY_TO_CORE.get(key, key)
        if core_key not in fields:
            fields[core_key] = val
    # 2) 中文结构化正则(_DESC_FIELD_PATTERNS): 覆盖无冒号/特殊格式字段
    #    映射到 _core 规范键, 不覆盖第 1 步已提取的字段
    for zh_key, pattern in _DESC_FIELD_PATTERNS.items():
        core_key = _PROPERTY_KEY_MAP.get(_normalize_key(zh_key)) or _DESC_KEY_TO_CORE.get(zh_key)
        if not core_key or core_key in fields:
            continue
        m = pattern.search(text)
        if not m:
            continue
        val = next((g.strip() for g in m.groups() if g and g.strip()), "")
        val = _normalize_value(val)
        if val:
            fields[core_key] = val
    # 3) 中文 `键：值` 干净键值对扫描(补漏, 仅补缺): 土地用途/房屋结构/保证金/加价幅度...
    for k, v in _extract_desc_pairs(text).items():
        if k not in fields:
            fields[k] = v
    return fields


def clean_listing_data(data: dict) -> dict:
    """清洗 listing data。

    架构: property_info 为全集(来源可能是爬虫表格或 description 解析), _core 是从
    property_info 选出的高价值子集, 故始终满足 `_core ⊆ property_info`、`info ≥ core`。
    description 提取出的字段先回灌进 property_info(补缺, property_info 优先), 再统一由
    clean_property_info 挑选到 _core, 保证二者同源(description 为最终源头)。
    """
    if not data:
        return data
    out = dict(data)
    out.pop('__cleaned', None)
    # 强制重算: 清除旧 _core/_cleaned, 避免 stale 数据残留
    out.pop('_core', None)
    out.pop('_cleaned', None)

    # 1) 归一化 property_info 内部值
    prop = out.get('property_info')
    if isinstance(prop, str):
        try:
            import json
            prop = json.loads(prop)
        except Exception:
            prop = None
    if not isinstance(prop, dict):
        prop = {}
    prop = dict(prop)  # copy, 避免修改入参
    for k, v in list(prop.items()):
        if isinstance(v, str):
            prop[k] = _normalize_value(v)
    prop.pop('_core', None)
    prop.pop('_cleaned', None)

    # 2) 从 description 提取高价值字段, 回灌进 property_info(补缺, property_info 优先)
    #    -> property_info 成为全集, _core 再从中挑选, 保证 _core ⊆ property_info
    desc = out.get('description')
    if isinstance(desc, str):
        desc = _normalize_value(desc)
        out['description'] = desc
        for k, v in _extract_from_desc(desc).items():
            if k not in prop:
                prop[k] = v
    out['property_info'] = prop

    # 3) _core = 从 property_info 选出的高价值字段(子集)
    core = clean_property_info(prop)
    if core:
        # 将入选字段以规范键写回 property_info, 保证 `_core ⊆ property_info`
        # (property_info 仍保留其原始键, 故 info 为全集、core 为其子集)
        for k, v in core.items():
            prop.setdefault(k, v)
        out['_core'] = core
        out['_cleaned'] = True
    return out

