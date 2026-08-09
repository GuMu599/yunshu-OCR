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
from .table_html import (
    MERGE_EXPAND,
    Table,
    TableCell,
    make_table,
    parse_html_table,
    table_to_html,
    table_to_md,
)

QUALITY_GATE = 0.6
MODEL_GATE = 0.5
TABLE_MARKER = "<!-- table: full structure in layout.json -->"
IMG_MARKER = "<!-- table: unrecognized, image fallback -->"


# ---------------------------------------------------------------------------
# 原有逻辑 (PyMuPDF find_tables)
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# 几何重建 (Tier 1): 词级坐标 → Table
# ---------------------------------------------------------------------------


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
    """按 y-center 聚行, 容差 = 0.6 × 中位字高; 行内按 x0 排序."""
    if not items:
        return []
    tol = _median_height(items) * 0.6
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

    保守启发式: 仅当下一行 x 跨嵌套在上一行内, 且垂直间隙 ≤ 0.25×中位行高
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
        if row_x0 >= prev_x0 - 2.0 and row_x1 <= prev_x1 + 2.0 and -2.0 <= gap <= 0.25 * med_h:
            merged[-1] = prev + row
        else:
            merged.append(row)
    return [sorted(r, key=lambda i: i.x0) for r in merged]


def _column_clusters(items: list[WordItem]) -> dict[int, int]:
    """按区间重叠聚列 (interval graph 连通分量).

    同列的词 x 区间互相重叠/相邻 (容差 = 一个空格宽, max(4pt, 0.25×中位字宽)):
    "Col A" 这类多词表头会被并回同一格; 右对齐数字列尽管 x0 分散, x1 收敛到
    同一右缘仍归同列。典型列间距远大于空格宽, 不会误并相邻列。
    """
    tol = max(4.0, 0.25 * _median_width(items))
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


def _is_numeric(text: str) -> bool:
    t = text.replace(",", "").replace(".", "").replace("%", "").replace("-", "").replace(" ", "")
    return bool(t) and t.isdigit()


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
    if len(items) < 4:
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


def _structure_quality(table: Table, items: list[WordItem]) -> float:
    """确定性质量分 [0,1]: 0.6×列垂直支撑覆盖率 + 0.4×填充率.

    列垂直支撑 = 至少 2 个不同行有词的列占比, 抑制单行伪列。
    """
    rows = _merge_wrapped_lines(_row_cluster(items))
    idx_of = {id(it): i for i, it in enumerate(items)}
    row_idx = [[idx_of[id(it)] for it in row] for row in rows]
    col_of = _column_clusters(items)
    col_rows: dict[int, set[int]] = {}
    for ri, row in enumerate(row_idx):
        for i in row:
            col_rows.setdefault(col_of[i], set()).add(ri)
    n_cols = (max(col_of.values()) + 1) if col_of else 0
    supported = sum(1 for c in col_rows if len(col_rows[c]) >= 2)
    coverage = supported / max(1, n_cols)
    fill = table.filled_count() / max(1, table.rows * table.cols)
    return round(min(1.0, 0.6 * coverage + 0.4 * fill), 3)


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


_CAPTION_RE = None  # 延迟初始化 (避免 import re 顶部开销)


def _block_table_like(text: str) -> bool:
    """文本块是否像表格数据.

    排除表题/图题 (表 N / Table N / Fig. N)。多行块: 平均行短 (looks_like_table_data);
    单行块: ≥3 token 且含 ≥1 数字 (宽数字表行 / 简单表行)。
    """
    global _CAPTION_RE
    import re  # noqa: PLC0415

    if _CAPTION_RE is None:
        _CAPTION_RE = re.compile(r"^\s*(表\s*\d+|Table\s*\d+|TABLE\s*\d+|Fig\.?\s*\d+|Figure\s*\d+)")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return False
    if _CAPTION_RE.match(lines[0]):
        return False
    if len(lines) >= 3:
        return looks_like_table_data(text)
    tokens = text.split()
    if len(tokens) >= 3:
        return sum(1 for t in tokens if _is_numeric(t)) >= 1
    return len(text.strip()) < 30


def detect_text_table_candidates(page, *, min_blocks: int = 4, gap: float = 20.0,
                                 top_margin: float = 0.03, bottom_margin: float = 0.08) -> list[list[float]]:
    """从原生文字块找无框表格候选区域 (YOLO 漏检补丁).

    块级检测: 按 y 排序后, 竖直相邻 (间隙 ≤ gap) 且水平重叠的表格数据块聚成
    一个候选; 组 y 跨度内并入非表数据块 (元素列标签) 得覆盖整表的 bbox。
    题注/散文块排除; 页眉页脚带 (top/bottom margin) 排除 —— 页脚词会桥接
    相邻列导致误合并 (如页码 "157102-4" 横跨 C11/C12, 使两列并成一格)。
    返回 list[bbox]。
    """
    ph = page.rect.height
    top_band = ph * top_margin
    bottom_band = ph * (1 - bottom_margin)
    blocks = [
        b for b in page.get_text("blocks")
        if b[6] == 0 and b[4].strip()
        and top_band <= (b[1] + b[3]) / 2 <= bottom_band
    ]
    blocks.sort(key=lambda b: b[1])  # get_text("blocks") 非 y 序
    like = [_block_table_like(b[4]) for b in blocks]
    cands: list[list[float]] = []
    i, n = 0, len(blocks)
    while i < n:
        if not like[i]:
            i += 1
            continue
        group_idx = [i]
        y1 = blocks[i][3]
        j = i + 1
        while j < n and blocks[j][1] - y1 <= gap:
            if like[j] and min(blocks[j][2], blocks[group_idx[-1]][2]) > max(blocks[j][0], blocks[group_idx[-1]][0]):
                group_idx.append(j)
                y1 = max(y1, blocks[j][3])
            j += 1
        if len(group_idx) >= min_blocks:
            gy0 = min(blocks[k][1] for k in group_idx)
            in_span = [k for k in range(i, j) if gy0 - 2 <= (blocks[k][1] + blocks[k][3]) / 2 <= y1 + 2]
            cands.append([
                min(blocks[k][0] for k in in_span), gy0,
                max(blocks[k][2] for k in in_span), y1,
            ])
        i = j
    return cands


def _is_graph_region(page, rect, threshold: int = 50) -> bool:
    """区域矢量绘图元素过多 → 图表而非表格 (真实表格只有个位数网格线, 图表有上百条曲线).

    返回 True → 调用方直接降级 (不把图表硬建成表格)。
    """
    import fitz  # noqa: PLC0415

    r = fitz.Rect(*rect)
    count = 0
    for d in page.get_drawings():
        if fitz.Rect(d["rect"]).intersects(r):
            count += 1
            if count > threshold:
                return True
    return False


def merge_table_items(a: dict, b: dict) -> dict | None:
    """把两个表格 item 合并为一个 (跨页续表).

    条件: 两者都有 html, 列数一致。若 b 首行与 a 首行相同 (重复表头) 则去掉。
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


def _prose_like_table(frag: dict) -> bool:
    """表格片段是否其实是散文/公式区被误建成表.

    真实表格细胞短 (数字/标签 ~5-10 字符); 双栏散文每格是一整句 (>14 字符)。
    判定: 平均细胞长 >14, 或 >14 字符的长细胞占比 ≥30% (公式碎片会拉低均值,
    故辅以占比判据, 防公式+散文混合区漏判)。
    """
    html = frag.get("html")
    if not html:
        return False
    t = parse_html_table(html)
    if t is None:
        return True  # 无法解析 → 不信任
    lens = [len(c.text) for c in t.cells.values() if c.text.strip()]
    if not lens:
        return True
    mean = sum(lens) / len(lens)
    long_frac = sum(1 for L in lens if L > 14) / len(lens)
    return mean > 14 or long_frac >= 0.3


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


def _sane_text_table(md: str, native: list[WordItem]) -> bool:
    """PyMuPDF text 策略的列数应与原生每行词数吻合 (防轴标签/TOC 幻觉出多列)."""
    lines = [l for l in md.splitlines() if l.strip().startswith("|")]
    if len(lines) < 2:
        return False
    cols = max(len(l.strip().strip("|").split("|")) for l in lines)
    rows = _row_cluster(native)
    if not rows:
        return False
    max_wpr = max(len(r) for r in rows)
    return cols <= max(2, max_wpr + 2)


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
    q = _structure_quality(table, items)
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
) -> dict | None:
    """策略阶梯 → item fragment dict | None (None → pipeline 存表格图片).

    每级有质量门, 低质降级下一级, 绝不出错硬猜。
    """
    import fitz  # noqa: PLC0415

    rect = fitz.Rect(*rect) & page.rect
    if rect.is_empty:
        return None
    r = [rect.x0, rect.y0, rect.x1, rect.y1]

    # 0. 图表守卫: 矢量线过多 → 图表而非表格 (YOLO 高置信度把曲线图误判为 table)
    if _is_graph_region(page, r):
        return None

    native = native_word_items(page, rect)

    # 1. 原生文字几何重建 (确定性, 文本坐标即真值; 修复 PyMuPDF 幻影列)
    if len(native) >= 4:
        frag = _geometry_fragment(native, "geometry_native", merge_policy)
        if frag is not None:
            return frag

    # 2. 有框文字表 (PyMuPDF lines, 几何失败时兜底)
    md = find_table_ruled(page, r)
    if md:
        return _fragment("pymupdf", md)

    # 3. PyMuPDF text 策略 (无框文字表, 需词数充足且列数合理)
    if len(native) >= 6 and looks_like_table_data(_native_text(native)):
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
