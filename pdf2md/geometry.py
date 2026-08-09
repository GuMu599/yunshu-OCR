"""几何工具 — bbox 相交等共享函数 (消除多处拷贝).

此前 tables._intersection_area / pipeline._overlaps_any / layout._tables_touch /
benchmark._intersect 各写一份 bbox 相交逻辑, 现统一到此处。
"""

from __future__ import annotations


def intersect_area(a, b) -> float:
    """两个 [x0,y0,x1,y1] bbox 的交集面积; 不相交返回 0."""
    dx = min(a[2], b[2]) - max(a[0], b[0])
    dy = min(a[3], b[3]) - max(a[1], b[1])
    if dx <= 0 or dy <= 0:
        return 0.0
    return dx * dy


def overlap_ratio(a, b) -> float:
    """a 被 b 覆盖的面积占比 (a 面积内)."""
    area = intersect_area(a, b)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    return area / area_a if area_a > 0 else 0.0


def overlaps_any(a, others, thr: float = 0.5) -> bool:
    """a 是否与 others 任一区域重叠 ≥ thr 比例."""
    for b in others:
        if overlap_ratio(a, b) >= thr:
            return True
    return False


def boxes_touch(a, b, gap: float = 20.0) -> bool:
    """两框是否应合并: 面积重叠, 或竖直相邻 (间隙 ≤ gap) 且水平重叠."""
    dx = min(a[2], b[2]) - max(a[0], b[0])
    dy = min(a[3], b[3]) - max(a[1], b[1])
    if dx > 0 and dy > 0:
        return True
    if dx > 0:
        if a[3] <= b[1]:
            vgap = b[1] - a[3]
        elif b[3] <= a[1]:
            vgap = a[1] - b[3]
        else:
            vgap = 0.0
        return vgap <= gap
    return False
