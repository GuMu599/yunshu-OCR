"""跨页续表合并 — 表头相似度/列类型签名门槛, 防不同表误并.

从 tables.py 拆分 (God Module 治理)。
"""

from __future__ import annotations

from .table_config import (
    COL_SIG_TOL,
    HEADER_CELL_LEN,
    HEADER_NUMERIC_FRAC,
    HEADER_SIM_TOL,
    TABLE_MARKER,
)
from .table_geometry import _is_numeric, _numeric_align_from_grid
from .table_html import Table, make_table, parse_html_table, table_to_html, table_to_md


def _col_type_sig(table: Table) -> list[float]:
    """每列数字占比 → 列类型签名 (跨页合并判同表依据)."""
    sig: list[float] = []
    for c in range(table.cols):
        vals = [table.text_at(r, c).strip() for r in range(table.rows) if table.text_at(r, c).strip()]
        sig.append(sum(1 for v in vals if _is_numeric(v)) / len(vals) if vals else 0.0)
    return sig


def _row_header_like(table: Table, r: int = 0) -> bool:
    """某行是否表头样: 非空格多为短文本、数字占比低."""
    cells = [table.text_at(r, c).strip() for c in range(table.cols)]
    cells = [c for c in cells if c]
    if not cells:
        return False
    numeric = sum(1 for c in cells if _is_numeric(c))
    return numeric / len(cells) < HEADER_NUMERIC_FRAC and all(len(c) < HEADER_CELL_LEN for c in cells)


def _header_sim(a: str, b: str) -> bool:
    """表头文本归一化后字符重合度 > HEADER_SIM_TOL (防不同标题表误并)."""
    import re  # noqa: PLC0415

    norm = lambda s: re.sub(r"[\d\s.·,;:()\[\]'\"\-]+", "", (s or "").lower())
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    sa, sb = set(na), set(nb)
    return len(sa & sb) / len(sa | sb) > HEADER_SIM_TOL


def merge_table_items(a: dict, b: dict) -> dict | None:
    """把两个表格 item 合并为一个 (跨页续表).

    条件: 两者都有 html, 列数一致; 列类型签名一致; 双表首行都表头样则表头须相似
    (防不同表同列数误并)。若 b 首行与 a 首行相同 (重复表头) 则去掉。
    返回合并后的 item dict (沿用 a 的 bbox/id), 不可合并返回 None。
    """
    ha = a.get("html")
    hb = b.get("html")
    if not ha or not hb:
        return None
    ta = parse_html_table(ha)
    tb = parse_html_table(hb)
    if ta is None or tb is None or ta.cols != tb.cols:
        return None
    # 列类型签名一致 (数字列/文本列布局不同 → 不是同一张表)
    sig_a = _col_type_sig(ta)
    sig_b = _col_type_sig(tb)
    if max(abs(x - y) for x, y in zip(sig_a, sig_b)) > COL_SIG_TOL:
        return None
    # 双表首行都表头样 → 表头须相似 (防不同标题表误并, 如 Revenue vs Cost)
    if _row_header_like(ta) and _row_header_like(tb):
        a_head = " ".join(ta.text_at(0, c) for c in range(ta.cols))
        b_head = " ".join(tb.text_at(0, c) for c in range(tb.cols))
        if not _header_sim(a_head, b_head):
            return None
    ga = ta.expanded()
    gb = tb.expanded()
    if not ga or not gb:
        return None
    start_b = 1 if gb[0] == ga[0] else 0  # b 首行重复表头 → 丢弃
    rows = ga + gb[start_b:]
    merged = make_table(rows)
    merged.align = _numeric_align_from_grid(rows)  # 数字列右对齐 (HTML 不含对齐信息)
    md = table_to_md(merged)
    if md is None:
        return None
    return {
        "type": "table",
        "markdown": f"{TABLE_MARKER}\n{md}",
        "text": "\n".join(" ".join(r) for r in rows),
        "html": table_to_html(merged),
        "structure_quality": None,
        "source": "merged_cross_page",
        "confidence": None,
    }
