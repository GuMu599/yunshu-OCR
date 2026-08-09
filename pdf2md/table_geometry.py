"""表格几何重建 — 词级坐标 → Table (行列聚类/对齐/质量).

从 tables.py 拆分 (God Module 治理): 纯几何/词提取逻辑, 不依赖检测/合并/阶梯。
"""

from __future__ import annotations

from dataclasses import dataclass

from . import ocr as ocr_mod
from .table_config import (
    COL_GAP_FRAC,
    MIN_TABLE_WORDS,
    QUALITY_COV_W,
    QUALITY_FILL_W,
    ROW_TOL_FRAC,
    WRAP_GAP_FRAC,
)
from .table_html import Table, TableCell


@dataclass
class WordItem:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float | None = None


def native_word_items(page, rect) -> list[WordItem]:
    """区域原生文字词项 (PDF 点坐标, 直接可用)."""
    import fitz  # noqa: PLC0415

    words = page.get_text("words", clip=fitz.Rect(*rect))
    return [WordItem(w[4], float(w[0]), float(w[1]), float(w[2]), float(w[3])) for w in words]


def ocr_word_items(page, rect, dpi: int = 300) -> list[WordItem]:
    """区域 OCR 词项 (框已换算为 PDF 点)."""
    return [
        WordItem(l.text, l.box_pdf[0], l.box_pdf[1], l.box_pdf[2], l.box_pdf[3], l.confidence)
        for l in ocr_mod.ocr_region_with_boxes(page, rect, dpi)
    ]


def _median(items, key):
    vals = sorted(key(i) for i in items)
    return vals[len(vals) // 2]


def _median_height(items) -> float:
    return max(4.0, _median(items, lambda i: max(2.0, i.y1 - i.y0)))


def _median_width(items) -> float:
    return max(3.0, _median(items, lambda i: max(2.0, i.x1 - i.x0)))


def _row_cluster(items: list[WordItem]) -> list[list[WordItem]]:
    """按 y-center 聚行, 容差 = ROW_TOL_FRAC × 中位字高; 行内按 x0 排序."""
    if not items:
        return []
    tol = _median_height(items) * ROW_TOL_FRAC
    ordered = sorted(items, key=lambda i: (i.y0 + i.y1) / 2)
    rows: list[list[WordItem]] = [[ordered[0]]]
    cur_y = (ordered[0].y0 + ordered[0].y1) / 2
    for it in ordered[1:]:
        yc = (it.y0 + it.y1) / 2
        if abs(yc - cur_y) <= tol:
            rows[-1].append(it)
        else:
            rows.append([it])
            cur_y = yc
    return [sorted(r, key=lambda i: i.x0) for r in rows]


def _merge_wrapped_lines(rows: list[list[WordItem]]) -> list[list[WordItem]]:
    """把换行拆散的多行格并回上一行.

    保守启发式: 仅当下一行 x 跨嵌套在上一行内, 且垂直间隙 ≤ WRAP_GAP_FRAC×中位行高
    (真换行通常间隙≈0)。相邻数据行间隙更大, 不会误并。误并/漏并由质量门兜底。
    """
    if len(rows) < 2:
        return rows
    all_items = [it for row in rows for it in row]
    med_h = _median_height(all_items)
    merged: list[list[WordItem]] = [rows[0]]
    for row in rows[1:]:
        prev = merged[-1]
        prev_x0 = min(i.x0 for i in prev)
        prev_x1 = max(i.x1 for i in prev)
        row_x0 = min(i.x0 for i in row)
        row_x1 = max(i.x1 for i in row)
        gap = min(i.y0 for i in row) - max(i.y1 for i in prev)
        if row_x0 >= prev_x0 - 2.0 and row_x1 <= prev_x1 + 2.0 and -2.0 <= gap <= WRAP_GAP_FRAC * med_h:
            merged[-1] = prev + row
        else:
            merged.append(row)
    return [sorted(r, key=lambda i: i.x0) for r in merged]


def _column_clusters(items: list[WordItem]) -> dict[int, int]:
    """按区间重叠聚列 (interval graph 连通分量).

    同列的词 x 区间互相重叠/相邻 (容差 = 一个空格宽, max(4pt, COL_GAP_FRAC×中位字宽)):
    "Col A" 这类多词表头会被并回同一格; 右对齐数字列尽管 x0 分散, x1 收敛到
    同一右缘仍归同列。典型列间距远大于空格宽, 不会误并相邻列。
    """
    tol = max(4.0, COL_GAP_FRAC * _median_width(items))
    order = sorted(range(len(items)), key=lambda i: items[i].x0)
    clusters: list[list] = []  # [min_x0, max_x1, indices]
    col_of: dict[int, int] = {}
    for i in order:
        it = items[i]
        placed = False
        for ci, cl in enumerate(clusters):
            if it.x0 <= cl[1] + tol and it.x1 >= cl[0] - tol:
                cl[0] = min(cl[0], it.x0)
                cl[1] = max(cl[1], it.x1)
                cl[2].append(i)
                col_of[i] = ci
                placed = True
                break
        if not placed:
            clusters.append([it.x0, it.x1, [i]])
            col_of[i] = len(clusters) - 1
    return col_of


def _is_numeric(text: str) -> bool:
    t = text.replace(",", "").replace(".", "").replace("%", "").replace("-", "").replace(" ", "")
    return bool(t) and t.isdigit()


def _numeric_align_from_grid(rows: list[list[str]]) -> list[str | None] | None:
    """文本网格 → 每列右对齐标记 (非空格 >60% 数字 → right)."""
    if not rows:
        return None
    cols = max(len(r) for r in rows)
    align: list[str | None] = []
    for c in range(cols):
        vals = [r[c].strip() for r in rows if c < len(r) and r[c].strip()]
        if len(vals) >= 3 and sum(1 for v in vals if _is_numeric(v)) / len(vals) > 0.6:
            align.append("right")
        else:
            align.append(None)
    return align


def _detect_align(items: list[WordItem], row_idx, col_of: dict[int, int], n_cols: int, tol: float) -> list[str | None]:
    align: list[str | None] = [None] * n_cols
    for c in range(n_cols):
        x1s: list[float] = []
        num = 0
        total = 0
        for row in row_idx:
            for i in row:
                if col_of.get(i) == c:
                    x1s.append(items[i].x1)
                    total += 1
                    if _is_numeric(items[i].text):
                        num += 1
        if total >= 3 and num / total > 0.6 and x1s and (max(x1s) - min(x1s)) <= max(2.0, tol):
            align[c] = "right"
    return align


def rebuild_table_from_boxes(items: list[WordItem]) -> Table | None:
    """词级坐标 → Table (1x1 span). 退化 (行/列/填充不足) 返回 None."""
    if len(items) < MIN_TABLE_WORDS:
        return None
    rows = _merge_wrapped_lines(_row_cluster(items))
    if len(rows) < 2:
        return None
    idx_of = {id(it): i for i, it in enumerate(items)}
    row_idx = [[idx_of[id(it)] for it in row] for row in rows]

    col_of = _column_clusters(items)
    n_cols = (max(col_of.values()) + 1) if col_of else 0
    if n_cols < 2:
        return None

    cells: dict[tuple[int, int], TableCell] = {}
    for ri, row in enumerate(row_idx):
        by_col: dict[int, list[int]] = {}
        for i in row:
            by_col.setdefault(col_of[i], []).append(i)
        for c, idxs in by_col.items():
            text = " ".join(items[i].text for i in idxs).strip()
            confs = [items[i].conf for i in idxs if items[i].conf is not None]
            conf = sum(confs) / len(confs) if confs else None
            cells[(ri, c)] = TableCell(ri, c, text=text, confidence=conf)

    table = Table(len(row_idx), n_cols, cells)
    table.align = _detect_align(items, row_idx, col_of, n_cols, _median_width(items))
    return table


def _structure_quality(table: Table) -> float:
    """确定性质量分 [0,1]: QUALITY_COV_W×列垂直支撑覆盖率 + QUALITY_FILL_W×填充率.

    列垂直支撑 = 至少 2 个不同行有内容的列占比, 抑制单行伪列。
    直接从 table.cells 计算 (复用几何重建结果, 不再重跑聚类)。
    """
    col_rows: dict[int, set[int]] = {}
    for (r, c), cell in table.cells.items():
        if cell.text.strip():
            col_rows.setdefault(c, set()).add(r)
    n_cols = table.cols
    supported = sum(1 for c in range(n_cols) if len(col_rows.get(c, ())) >= 2)
    coverage = supported / max(1, n_cols)
    fill = table.filled_count() / max(1, table.rows * table.cols)
    return round(min(1.0, QUALITY_COV_W * coverage + QUALITY_FILL_W * fill), 3)
