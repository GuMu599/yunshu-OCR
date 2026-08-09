"""表格中间数据模型与 HTML/Markdown 互转.

几何重建与结构模型都产出同一个 ``Table``, 后续 MD / HTML / 质量 / 置信度共享一条路径.
MD 无 rowspan/colspan 语法 → 合并单元格用「展开复制」(expand, 默认, 数据零丢失)
或「空白占位」(blank) 表达; 无损 HTML 始终可由 table_to_html 还原, 供 layout.json 旁路.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

MERGE_EXPAND = "expand"
MERGE_BLANK = "blank"

_CELL_TAGS = {"td", "th"}
_TABLE_STRUCT_TAGS = {"table", "tr", "thead", "tbody", "tfoot"}


@dataclass
class TableCell:
    """单元格. row/col 为锚点 (左上角), rowspan/colspan ≥ 1."""

    row: int
    col: int
    rowspan: int = 1
    colspan: int = 1
    text: str = ""
    confidence: float | None = None


@dataclass
class Table:
    """行 x 列的矩形表格; cells 以锚点 (row, col) 索引."""

    rows: int
    cols: int
    cells: dict[tuple[int, int], TableCell] = field(default_factory=dict)
    align: list[str | None] | None = None  # 每列 "left" | "right" | None

    def cell(self, row: int, col: int) -> TableCell | None:
        """覆盖 (row, col) 的单元格 (含 span 扩展)."""
        for (r, c), cell in self.cells.items():
            if r <= row < r + cell.rowspan and c <= col < c + cell.colspan:
                return cell
        return None

    def text_at(self, row: int, col: int) -> str:
        cell = self.cell(row, col)
        return cell.text if cell else ""

    def filled_count(self) -> int:
        return sum(1 for cell in self.cells.values() if cell.text.strip())

    def expanded(self) -> list[list[str]]:
        """展开成 rows x cols 文本网格 (span 复制). 防御性钳制到表格边界."""
        grid = [[""] * self.cols for _ in range(self.rows)]
        for (r, c), cell in self.cells.items():
            for rr in range(r, min(r + cell.rowspan, self.rows)):
                for cc in range(c, min(c + cell.colspan, self.cols)):
                    grid[rr][cc] = cell.text
        return grid


def make_table(texts: list[list[str]]) -> Table:
    """从文本网格构造 1x1 单元格表格 (几何重建的产物)."""
    rows = len(texts)
    cols = max((len(r) for r in texts), default=0)
    cells: dict[tuple[int, int], TableCell] = {}
    for r, row in enumerate(texts):
        for c in range(cols):
            t = row[c].strip() if c < len(row) else ""
            cells[(r, c)] = TableCell(r, c, text=t)
    return Table(rows, cols, cells)


def _attr_int(attrs, name: str, default: int = 1) -> int:
    for k, v in attrs:
        if k == name:
            try:
                return max(1, int(str(v).strip()))
            except (TypeError, ValueError):
                return default
    return default


def _normalize_text(s: str) -> str:
    return re.sub(r"[ \t]+", " ", s.strip())


def _first_free_col(grid: list[list[TableCell | None]], row: int) -> int:
    row_cells = grid[row] if row < len(grid) else []
    c = 0
    while c < len(row_cells) and row_cells[c] is not None:
        c += 1
    return c


class _TableHTMLParser(HTMLParser):
    """容错的表格 HTML 解析: 拼成 grid + cells. 畸形输入不抛错, 退化为矩形网格."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._has_table = False
        self._grid: list[list[TableCell | None]] = []
        self._cells: dict[tuple[int, int], TableCell] = {}
        self._row_index = -1
        self._in_cell = False
        self._cell_text: list[str] = []
        self._cell_rowspan = 1
        self._cell_colspan = 1

    # -- HTMLParser hooks -------------------------------------------------
    def handle_starttag(self, tag, attrs) -> None:  # noqa: ANN001
        t = tag.lower()
        if t == "table":
            self._has_table = True
        elif t == "tr":
            self._row_index += 1
        elif t in _CELL_TAGS:
            self._in_cell = True
            self._cell_text = []
            self._cell_rowspan = _attr_int(attrs, "rowspan")
            self._cell_colspan = _attr_int(attrs, "colspan")
        # 其余标签 (thead/tbody/cell 内嵌 span/b 等) 忽略; 文字直接进当前 cell

    def handle_endtag(self, tag) -> None:  # noqa: ANN001
        t = tag.lower()
        if t == "table":
            self._in_cell = False
        elif t == "tr":
            self._in_cell = False
        elif t in _CELL_TAGS and self._in_cell:
            self._close_cell()
            self._in_cell = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_text.append(data)

    # -- internal ---------------------------------------------------------
    def _close_cell(self) -> None:
        row = self._row_index
        text = _normalize_text("".join(self._cell_text))
        while len(self._grid) <= row:
            self._grid.append([])
        col = _first_free_col(self._grid, row)
        cell = TableCell(row, col, self._cell_rowspan, self._cell_colspan, text)
        self._cells[(row, col)] = cell
        for rr in range(row, row + cell.rowspan):
            while len(self._grid) <= rr:
                self._grid.append([])
            need = col + cell.colspan
            while len(self._grid[rr]) < need:
                self._grid[rr].append(None)
            for cc in range(col, col + cell.colspan):
                self._grid[rr][cc] = cell


def parse_html_table(html: str) -> Table | None:
    """解析表格 HTML → Table. 无表格 / 全空 / 解析失败返回 None."""
    if not html or "<table" not in html.lower():
        return None
    parser = _TableHTMLParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return None
    if not parser._has_table or not parser._cells:
        return None
    # rows/cols 覆盖所有单元格的 span 范围 → expanded()/cell() 永不越界
    rows = max((r + cell.rowspan for (r, _), cell in parser._cells.items()), default=0)
    cols = max((c + cell.colspan for (_, c), cell in parser._cells.items()), default=0)
    if rows < 1 or cols < 1:
        return None
    return Table(rows, cols, parser._cells)


# ---------- Markdown 输出 ----------


def _escape_md(text: str) -> str:
    return text.replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def _cell_text_md(table: Table, r: int, c: int, merge_policy: str) -> str:
    cell = table.cell(r, c)
    if cell is None:
        return ""
    if merge_policy == MERGE_BLANK and (cell.row, cell.col) != (r, c):
        return ""  # 空白占位: 仅锚点保留文本
    return _escape_md(cell.text.strip())


def table_to_md(table: Table, merge_policy: str = MERGE_EXPAND) -> str | None:
    """Table → Markdown 管道表. 退化表格 (0 行/列) 返回 None."""
    if table.rows < 1 or table.cols < 1:
        return None
    align = table.align or [None] * table.cols
    lines: list[str] = []
    header = [_cell_text_md(table, 0, c, merge_policy) for c in range(table.cols)]
    lines.append("| " + " | ".join(header) + " |")
    sep: list[str] = []
    for c in range(table.cols):
        a = align[c] if c < len(align) else None
        sep.append(":---" if a == "left" else "---:" if a == "right" else "---")
    lines.append("| " + " | ".join(sep) + " |")
    for r in range(1, table.rows):
        row = [_cell_text_md(table, r, c, merge_policy) for c in range(table.cols)]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


# ---------- 无损 HTML 输出 ----------


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def table_to_html(table: Table) -> str:
    """无损 HTML (rowspan/colspan > 1 才显式), 用于 layout.json 旁路."""
    parts = ["<table>"]
    for r in range(table.rows):
        parts.append("<tr>")
        c = 0
        while c < table.cols:
            cell = table.cell(r, c)
            if cell is None:
                parts.append("<td></td>")
                c += 1
                continue
            if (cell.row, cell.col) == (r, c):
                attrs = ""
                if cell.rowspan > 1:
                    attrs += f' rowspan="{cell.rowspan}"'
                if cell.colspan > 1:
                    attrs += f' colspan="{cell.colspan}"'
                parts.append(f"<td{attrs}>{_escape_html(cell.text)}</td>")
            c += 1
        parts.append("</tr>")
    parts.append("</table>")
    return "".join(parts)
