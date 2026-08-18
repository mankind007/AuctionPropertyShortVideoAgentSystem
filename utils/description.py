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
                pairs[cur_key] = " ".join(cur_val).strip()
            cur_key = m.group(1).strip()
            cur_val = []
            continue
        m2 = re.match(r"^(.+?)[：:]\s*(.+)$", s)
        if m2:
            if cur_key and cur_val:
                pairs[cur_key] = " ".join(cur_val).strip()
            cur_key = m2.group(1).strip()
            cur_val = [m2.group(2).strip()]
            continue
        if cur_key:
            cur_val.append(s)
    if cur_key and cur_val:
        pairs[cur_key] = " ".join(cur_val).strip()
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
    seg = " ".join(seg.split()).strip()
    return seg if len(seg) >= 6 else raw


def _old_rule(raw: str, m: re.Match) -> str:
    seg = raw[m.end():]
    cut = _HEADER.search(seg)
    if cut:
        seg = seg[: cut.start()]
    seg = seg.strip()
    return seg if len(seg) >= 6 else raw


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