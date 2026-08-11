"""版面阅读顺序 — 基于栏距检测的块级重排.

第一性原理: 阅读顺序 = 人类视觉顺序.
- 多栏页: 左栏读完 (上→下) 再右栏 (上→下); 通栏元素 (标题/表格/公式/图) 按 y
  在其所在的"带"中插入, 并作为分栏分隔带。
- 单栏页: 无栏距 → 全局 (y, x) 序。
- 栏距 = 文字块 x 分布中干净的空带; 通过"通栏块 + 其余块按水平重叠聚栏"得到。

本函数对任意 [x0,y0,x1,y1] 形 box 通用 (文本块或 item bbox 均可)。
"""

from __future__ import annotations

_FULL_WIDTH_RATIO = 0.70  # 栏距检测时排除的宽块比例
_MIN_COLUMN_BLOCKS = 2    # 少于该块数不构成栏
_MIN_GUTTER = 12.0       # 栏距最小宽度
_GUTTER_COV_FRAC = 0.30  # 栏距覆盖阈值 = max(2, 栏最大覆盖 × 该比例)


def _split_columns(boxes):
    """box 集 → (通栏块, 栏列表[[box...]], 孤立块).

    第一性原理: 栏距 = 文字间的明显空行 (覆盖稀疏, 相对栏内覆盖低)。
    宽块 (标题/摘要/表格) 先排除避免掩盖栏距; 跨栏桥块 (公式/居中行) 覆盖稀疏,
    由相对阈值吸收; 取能使两侧各 ≥2 块的最宽空带为栏距。
    """
    if not boxes:
        return [], [], []
    content_w = max(b[2] for b in boxes) - min(b[0] for b in boxes)
    narrow = [b for b in boxes if (b[2] - b[0]) <= content_w * _FULL_WIDTH_RATIO]
    if len(narrow) < 4:
        return [], [], []
    xs = [b[0] for b in narrow] + [b[2] for b in narrow]
    xmin, xmax = int(min(xs)), int(max(xs))
    step = 2
    cov = [0] * ((xmax - xmin) // step + 1)
    max_cov = 0
    for b in narrow:
        lo = max(0, (int(b[0]) - xmin) // step)
        hi = min(len(cov) - 1, (int(b[2]) - xmin) // step)
        for i in range(lo, hi + 1):
            cov[i] += 1
    max_cov = max(cov)
    if max_cov < 3:
        return [], [], []  # 列覆盖太稀疏, 无法区分栏距与栏内部 → 单栏
    thr = max(2, round(max_cov * _GUTTER_COV_FRAC))

    # 低覆盖连续区 = 栏距候选
    gutters: list[tuple[float, float]] = []
    run_start: int | None = None
    for i, c in enumerate(cov):
        if c <= thr:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None and (i - run_start) * step >= _MIN_GUTTER:
                gutters.append((xmin + run_start * step, xmin + i * step))
            run_start = None
    if run_start is not None and (len(cov) - 1 - run_start) * step >= _MIN_GUTTER:
        gutters.append((xmin + run_start * step, xmax))

    # 取能有效分割 (两侧 ≥2 块) 的最宽栏距
    for g0, g1 in sorted(gutters, key=lambda g: -(g[1] - g[0])):
        mid = (g0 + g1) / 2
        left: list = []
        right: list = []
        crossing: list = []
        for b in boxes:
            cx = (b[0] + b[2]) / 2
            if b[0] < mid < b[2]:
                crossing.append(b)  # 横跨栏距 (标题/摘要/桥)
            elif cx < mid:
                left.append(b)
            else:
                right.append(b)
        if len(left) >= _MIN_COLUMN_BLOCKS and len(right) >= _MIN_COLUMN_BLOCKS:
            return crossing, [left, right], []
    return [], [], []


def page_gutter_mid(boxes) -> float | None:
    """块级检测栏距中点 (块多更稳健). 单栏返回 None."""
    _, cols, _ = _split_columns(boxes)
    if len(cols) < 2:
        return None
    l_max = max(b[2] for b in cols[0])
    r_min = min(b[0] for b in cols[1])
    return (l_max + r_min) / 2


def reading_order_rank(
    boxes, page_rect, gutter_mid=None, visual_anchors=None, structural_anchors=None
) -> dict[int, int]:
    """box 集 → 每个 box 的阅读顺序序号.

    通栏块 (跨栏距) 按 y 作分隔带; 栏块按 (带, 列序, y) 排序 (左栏读完再右栏)。
    gutter_mid 可由调用方用块级 page_gutter_mid() 预计算 (更稳健), 缺省自行检测。
    单栏 (无栏距) 退回全局 (y, x) 序。
    """
    if gutter_mid is None:
        gutter_mid = page_gutter_mid(boxes)
    if gutter_mid is None:
        return {id(b): i for i, b in enumerate(sorted(boxes, key=lambda b: (b[1], b[0])))}

    left: list = []
    right: list = []
    full: list = []
    content_w = (max(b[2] for b in boxes) - min(b[0] for b in boxes)) if boxes else 1.0
    natural_full = [b for b in boxes if (b[2] - b[0]) > 0.7 * content_w]
    visual_anchor_ids = {id(box) for box in (visual_anchors or [])}
    full_visual_anchors = [box for box in natural_full if id(box) in visual_anchor_ids]
    full_ids = {id(box) for box in natural_full}
    structural = [box for box in (structural_anchors or []) if id(box) not in full_ids]
    changed = True
    while changed:
        changed = False
        for candidate in structural:
            if id(candidate) in full_ids:
                continue
            for anchor in boxes:
                if id(anchor) not in full_ids or anchor[1] < candidate[3]:
                    continue
                if anchor[1] - candidate[3] <= 30.0:
                    full_ids.add(id(candidate))
                    changed = True
                    break
    companion_ids: set[int] = set()
    for candidate in boxes:
        if candidate in natural_full:
            continue
        candidate_width = candidate[2] - candidate[0]
        candidate_height = candidate[3] - candidate[1]
        if candidate_height > max(40.0, page_rect.height * 0.05):
            continue
        for anchor in full_visual_anchors:
            horizontal_overlap = max(0.0, min(candidate[2], anchor[2]) - max(candidate[0], anchor[0]))
            overlap_fraction = horizontal_overlap / max(1.0, candidate_width)
            vertical_gap = max(anchor[1] - candidate[3], candidate[1] - anchor[3], 0.0)
            if overlap_fraction >= 0.8 and vertical_gap <= 24.0:
                companion_ids.add(id(candidate))
                break
    for b in boxes:
        cx = (b[0] + b[2]) / 2
        if id(b) in full_ids or id(b) in companion_ids:
            full.append(b)  # 真通栏 (标题/摘要/图, 宽跨内容宽)
        elif cx < gutter_mid:
            left.append(b)
        else:
            right.append(b)
    if len(left) < _MIN_COLUMN_BLOCKS or len(right) < _MIN_COLUMN_BLOCKS:
        return {id(b): i for i, b in enumerate(sorted(boxes, key=lambda b: (b[1], b[0])))}

    full.sort(key=lambda b: (b[1], b[0]))
    left.sort(key=lambda b: (b[1], b[0]))
    right.sort(key=lambda b: (b[1], b[0]))

    remaining_left = left
    remaining_right = right
    ordered: list = []
    for anchor in full:
        anchor_y = anchor[1]
        above_left = [b for b in remaining_left if (b[1] + b[3]) / 2 < anchor_y]
        above_right = [b for b in remaining_right if (b[1] + b[3]) / 2 < anchor_y]
        ordered.extend(above_left)
        ordered.extend(above_right)
        remaining_left = [b for b in remaining_left if b not in above_left]
        remaining_right = [b for b in remaining_right if b not in above_right]
        ordered.append(anchor)
    ordered.extend(remaining_left)
    ordered.extend(remaining_right)
    return {id(b): i for i, b in enumerate(ordered)}
