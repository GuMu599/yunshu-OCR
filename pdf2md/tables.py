"""表格 → Markdown 表格.

用 PyMuPDF 内置 find_tables() (CPU, 无模型)。有框表格效果良好;
无结果或单行(表头残缺)返回 None, 由 pipeline 降级为图片。
跨页表格: v1 记 table_continues, v2 合并。
"""

from __future__ import annotations


def _intersection_area(a: list[float], b: list[float]) -> float:
    dx = min(a[2], b[2]) - max(a[0], b[0])
    dy = min(a[3], b[3]) - max(a[1], b[1])
    if dx <= 0 or dy <= 0:
        return 0.0
    return dx * dy


def _best_table(page, rect, strategy: str):
    tabs = page.find_tables(strategy=strategy)
    best = None
    best_area = 0.0
    for t in tabs.tables:
        area = _intersection_area(list(t.bbox), list(rect))
        if area > best_area:
            best_area = area
            best = t
    if best is not None and best.row_count > 1:
        return best
    return None


def _md_of(best) -> str | None:
    try:
        md = best.to_markdown()
    except Exception:
        return None
    if md and len(md.strip()) >= 8:
        return md.strip()
    return None


def find_table_ruled(page, rect) -> str | None:
    """有框/有网格线的真实表格 → MD. 用 lines 系列策略."""
    for strategy in ("lines", "lines_strict"):
        try:
            best = _best_table(page, rect, strategy)
        except Exception:
            continue
        if best is not None:
            md = _md_of(best)
            if md:
                return md
    return None


def find_table_text(page, rect) -> str | None:
    """无框文字型表格 → MD. 仅当调用方确认区域文字像表格数据时才用 (防双栏散文误拼)."""
    try:
        best = _best_table(page, rect, "text")
    except Exception:
        return None
    if best is not None:
        return _md_of(best)
    return None


def looks_like_table_data(raw: str) -> bool:
    """区域原生文字是否像表格数据 (多行且平均行长短).

    散文段落行很长 (>30), 表格数据行短; 这区分 YOLO 把散文误判为 table 的情况。
    空文字 (图片型表格) 也返回 False。
    """
    lines = [l.strip() for l in (raw or "").splitlines() if l.strip()]
    if len(lines) < 3:
        return False
    avg = sum(len(l) for l in lines) / len(lines)
    return avg < 30
