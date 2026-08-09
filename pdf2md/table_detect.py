"""表格检测/守卫启发式 — 文本块是否像表、无框表候选、图表/公式/散文守卫.

从 tables.py 拆分 (God Module 治理): 检测与内容类型守卫逻辑。
"""

from __future__ import annotations

import fitz

from .table_config import (
    CELL_LONG_FRAC,
    CELL_LONG_LEN,
    GRAPH_LINE_THRESHOLD,
    MATH_LINE_FRAC,
    PROSE_LINE_AVG,
)
from .table_geometry import WordItem, _is_numeric, _row_cluster
from .table_html import parse_html_table


def looks_like_table_data(raw: str) -> bool:
    """区域原生文字是否像表格数据 (多行且平均行长短).

    散文段落行很长 (>30), 表格数据行短; 这区分 YOLO 把散文误判为 table 的情况。
    空文字 (图片型表格) 也返回 False。
    """
    lines = [l.strip() for l in (raw or "").splitlines() if l.strip()]
    if len(lines) < 3:
        return False
    avg = sum(len(l) for l in lines) / len(lines)
    return avg < PROSE_LINE_AVG


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


def is_graph_region(page, rect, drawings=None, threshold: int = GRAPH_LINE_THRESHOLD) -> bool:
    """区域矢量绘图元素过多 → 图表而非表格 (真实表格只有个位数网格线, 图表有上百条曲线).

    返回 True → 调用方直接降级 (不把图表硬建成表格)。
    drawings 可传入预解析的 page.get_drawings() 结果 (页级缓存, 免每候选重复整页解析)。
    """
    import fitz  # noqa: PLC0415

    r = fitz.Rect(*rect)
    count = 0
    for d in drawings if drawings is not None else page.get_drawings():
        if fitz.Rect(d["rect"]).intersects(r):
            count += 1
            if count > threshold:
                return True
    return False


def is_raster_figure(page, rect, *, image_ratio: float = 0.6) -> bool:
    """区域是否主要是嵌入式位图 (照片/显微图) 且带图注 → 是图不是表.

    矢量图 (曲线) 由 is_graph_region 拦截; 位图照片 (CL 显微图等) 无矢量线,
    但含嵌入式图片 + 图注 (图 N / Fig. N)。避免被 OCR+几何重建建成假表。
    """
    import re  # noqa: PLC0415

    r = fitz.Rect(*rect)
    area = r.get_area()
    if area <= 0:
        return False
    img_area = 0.0
    for img in page.get_images(full=True):
        for ir in page.get_image_rects(img[0]):
            img_area += (ir & r).get_area()
    if img_area / area < image_ratio:
        return False  # 不是图片为主的区域
    native = page.get_text("text", clip=r)
    return bool(re.search(r"(图\s*\d+|Fig\.?\s*\d+|Figure\s*\d+)", native))


def prose_like_table(frag: dict) -> bool:
    """表格片段是否其实是散文/公式区被误建成表.

    真实表格细胞短 (数字/标签 ~5-10 字符); 双栏散文每格是一整句 (>14 字符)。
    判定: 平均细胞长 > CELL_LONG_LEN, 或 >CELL_LONG_LEN 的长细胞占比 ≥CELL_LONG_FRAC
    (公式碎片会拉低均值, 故辅以占比判据, 防公式+散文混合区漏判)。
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
    long_frac = sum(1 for L in lens if L > CELL_LONG_LEN) / len(lens)
    return mean > CELL_LONG_LEN or long_frac >= CELL_LONG_FRAC


def is_math_region(raw: str) -> bool:
    """区域原生文字是否数学密集 (LaTeX 命令/数学符号占 >MATH_LINE_FRAC 行) → 是公式区, 不应建成表格."""
    import re  # noqa: PLC0415

    lines = [l.strip() for l in (raw or "").splitlines() if l.strip()]
    if len(lines) < 2:
        return False
    math = sum(1 for l in lines if re.search(r"\\[a-zA-Z]+|[=^_]|\b(int|frac|sum|lim|nabla)\b", l))
    return math / len(lines) > MATH_LINE_FRAC


def sane_text_table(md: str, native: list[WordItem]) -> bool:
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
