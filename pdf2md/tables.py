"""表格 → Markdown 表格.

策略阶梯 (recognize_table, 第一性原理: 渲染像素是唯一必然真值来源):
  1. 有框文字表    PyMuPDF find_tables lines/lines_strict  (可靠快路径)
  2. 原生文字几何   词级坐标行列聚类重建                      (文字层存在)
  3. 无框文字表    PyMuPDF find_tables text 策略             (弱)
  4. 图片表救援    高 DPI 渲染 → RapidOCR box → 几何重建      (位图表, 零新模型)
  5. 复杂表升级    SLANet 结构模型 → HTML → 逐格内容         (合并单元格/多级表头)
  6. 最后防线      返回 None → pipeline 保存表格图片 + 标记

几何重建与结构模型统一产出 table_html.Table, 共享 MD/HTML/质量/置信度路径。
"""

from __future__ import annotations

from dataclasses import dataclass

from . import ocr as ocr_mod
from . import table_model
from .geometry import intersect_area  # noqa: F401
from .table_config import (
    CELL_LONG_FRAC, CELL_LONG_LEN, COL_SIG_TOL, GRAPH_LINE_THRESHOLD, HEADER_CELL_LEN,
    HEADER_NUMERIC_FRAC, HEADER_SIM_TOL, IMG_MARKER, MATH_LINE_FRAC, MIN_MD_LEN,
    MIN_TABLE_WORDS, MIN_TEXT_TABLE_WORDS, MODEL_GATE, PROSE_LINE_AVG, QUALITY_COV_W, QUALITY_FILL_W,
    QUALITY_GATE, TABLE_MARKER,
)
from .table_geometry import (  # noqa: F401 (再导出, 供外部 tables_mod.X 调用)
    WordItem, _column_clusters, _detect_align, _is_numeric, _median, _median_height,
    _median_width, _merge_wrapped_lines, _row_cluster, _structure_quality,
    _numeric_align_from_grid, native_word_items, ocr_word_items, rebuild_table_from_boxes,
)
from .table_detect import (
    _block_table_like,
    detect_text_table_candidates,
    is_graph_region as _is_graph_region,
    is_raster_figure as _is_raster_figure,
    is_math_region as _is_math_region,
    looks_like_table_data,
    prose_like_table as _prose_like_table,
    sane_text_table as _sane_text_table,
)
from .table_merge import (
    _col_type_sig, _header_sim, _row_header_like, merge_table_items,
)
from .table_html import (
    MERGE_EXPAND,
    Table,
    TableCell,
    make_table,
    parse_html_table,
    table_to_html,
    table_to_md,
)

# ---------------------------------------------------------------------------
# 原有逻辑 (PyMuPDF find_tables)
# ---------------------------------------------------------------------------

def _best_table(page, rect, strategy: str):
    tabs = page.find_tables(strategy=strategy)
    best = None
    best_area = 0.0
    for t in tabs.tables:
        area = intersect_area(list(t.bbox), list(rect))
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
    if md and len(md.strip()) >= MIN_MD_LEN:
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

# ---------------------------------------------------------------------------
# 几何重建 (Tier 1): 词级坐标 → Table
# ---------------------------------------------------------------------------

def _cell_conf_grid(table: Table) -> list[list[float | None]]:
    grid: list[list[float | None]] = []
    for r in range(table.rows):
        row: list[float | None] = []
        for c in range(table.cols):
            cell = table.cell(r, c)
            row.append(cell.confidence if cell else None)
        grid.append(row)
    return grid

def _mean_conf(table: Table) -> float | None:
    confs = [cell.confidence for cell in table.cells.values() if cell.confidence is not None]
    if not confs:
        return None
    return round(sum(confs) / len(confs), 3)

# ---------------------------------------------------------------------------
# 策略阶梯
# ---------------------------------------------------------------------------

def _fragment(source: str, md: str) -> dict:
    return {
        "type": "table",
        "markdown": md,
        "text": "",
        "html": None,
        "structure_quality": None,
        "cell_confidences": None,
        "source": source,
        "confidence": None,
    }

def _table_fragment(table: Table, source: str, quality: float, merge_policy: str) -> dict | None:
    md = table_to_md(table, merge_policy)
    if md is None:
        return None
    return {
        "type": "table",
        "markdown": f"{TABLE_MARKER}\n{md}",
        "text": "\n".join(" ".join(r) for r in table.expanded()),
        "html": table_to_html(table),
        "structure_quality": quality,
        "cell_confidences": _cell_conf_grid(table),
        "source": source,
        "confidence": _mean_conf(table),
    }

def _native_text(items: list[WordItem]) -> str:
    rows = _row_cluster(items)
    return "\n".join(" ".join(it.text for it in r) for r in rows)

def find_table_structured(page, rect, dpi: int = 300) -> Table | None:
    """结构模型路径: 渲染区域 → RapidTable (结构 + cell OCR) → HTML → Table.

    RapidTable 内部用 vendored RapidOCR 识别 cell 文字, 结构模型输出
    rowspan/colspan。模型缺失/失败 → table_model 返回 None → 本函数返回 None (调用方回退).
    """
    import fitz  # noqa: PLC0415

    rect = fitz.Rect(*rect) & page.rect
    if rect.is_empty:
        return None
    scale = max(1.0, float(dpi) / 72.0)
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
    result = table_model.TableModel.structure_table(pix.tobytes("png"))
    if not result:
        return None
    html, _cell_boxes_px = result

    from .table_html import parse_html_table

    return parse_html_table(html)

def _model_quality(table: Table) -> float:
    """结构模型结果质量: 需 ≥2×2 且填充率高 (防图注/轴标签被模型误建成表格)."""
    if table.rows < 2 or table.cols < 2:
        return 0.0
    fill = table.filled_count() / max(1, table.rows * table.cols)
    return round(min(1.0, fill + 0.2), 3)

def _geometry_fragment(items: list[WordItem], source: str, merge_policy: str) -> dict | None:
    """几何重建 → fragment. 质量低于门返回 None (调用方降级到模型/图片)."""
    table = rebuild_table_from_boxes(items)
    if table is None:
        return None
    q = _structure_quality(table)
    if q < QUALITY_GATE:
        return None
    return _table_fragment(table, source, q, merge_policy)

def recognize_table(
    page,
    rect,
    *,
    dpi: int = 300,
    do_ocr: bool = True,
    use_model: bool = True,
    merge_policy: str = MERGE_EXPAND,
    drawings=None,
) -> dict | None:
    """策略阶梯 → item fragment dict | None (None → pipeline 存表格图片).

    全函数: 单区域任何异常都隔离为 None (降级), 绝不拖垮整份 PDF 转换。
    drawings: 预解析的 page.get_drawings() (页级缓存, 免每候选重复整页解析)。
    """
    try:
        return _table_ladder(
            page, rect, dpi=dpi, do_ocr=do_ocr, use_model=use_model,
            merge_policy=merge_policy, drawings=drawings,
        )
    except Exception:  # noqa: BLE001
        return None

def _table_ladder(page, rect, *, dpi: int, do_ocr: bool, use_model: bool, merge_policy: str,
                  drawings=None) -> dict | None:
    """阶梯主体: 每级有质量门, 低质降级下一级, 绝不出错硬猜."""
    import fitz  # noqa: PLC0415

    rect = fitz.Rect(*rect) & page.rect
    if rect.is_empty:
        return None
    r = [rect.x0, rect.y0, rect.x1, rect.y1]

    # 0. 图表守卫: 矢量线过多 → 图表而非表格 (YOLO 高置信度把曲线图误判为 table)
    if _is_graph_region(page, r, drawings=drawings):
        return None
    # 0.5 位图图形守卫: 主要是嵌入式位图且带图注 → 图非表 (CL 显微图等)
    if _is_raster_figure(page, r):
        return None

    native = native_word_items(page, rect)
    native_raw = _native_text(native)

    # 0.5 数学守卫: 公式区 (含 LaTeX 命令/数学符号密集) 不应建成表格
    if _is_math_region(native_raw):
        return None

    # 1. 原生文字几何重建 (确定性, 文本坐标即真值; 修复 PyMuPDF 幻影列)
    if len(native) >= MIN_TABLE_WORDS:
        frag = _geometry_fragment(native, "geometry_native", merge_policy)
        if frag is not None:
            return frag

    # 2. 有框文字表 (PyMuPDF lines, 几何失败时兜底)
    md = find_table_ruled(page, r)
    if md:
        return _fragment("pymupdf", md)

    # 3. PyMuPDF text 策略 (无框文字表, 需词数充足、像表数据且非公式区)
    if len(native) >= MIN_TEXT_TABLE_WORDS and looks_like_table_data(native_raw) and not _is_math_region(native_raw):
        md = find_table_text(page, r)
        if md and _sane_text_table(md, native):
            return _fragment("pymupdf_text", md)

    # 4. 图片表救援: OCR → 几何重建
    if do_ocr:
        ocr_items = ocr_word_items(page, rect, dpi)
        if len(ocr_items) >= 4:
            frag = _geometry_fragment(ocr_items, "geometry_ocr", merge_policy)
            if frag is not None:
                return frag

    # 5. 结构模型 (复杂表: 几何失败时的最后尝试; 模型在这些无框合成表上不如几何, 故不作优先)
    if use_model:
        table = find_table_structured(page, rect, dpi)
        if table is not None:
            q = _model_quality(table)
            if q >= MODEL_GATE:
                frag = _table_fragment(table, "structure_model", q, merge_policy)
                if frag is not None:
                    return frag

    return None
