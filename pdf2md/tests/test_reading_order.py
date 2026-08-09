"""版面阅读顺序: 栏距检测 + 块级栏感知重排 (直接构造 [x0,y0,x1,y1] box, 隔离 PyMuPDF 行为)"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import fitz

from pdf2md.reading_order import page_gutter_mid, reading_order_rank  # noqa: E402


def _two_col_boxes():
    """双栏: 通栏标题 + 左栏 4 块 + 右栏 4 块, 栏距约 285-315. 返回 (boxes, name_by_id)."""
    boxes = [[90, 40, 500, 60]]  # 通栏标题
    names = {id(boxes[0]): "title"}
    for i in range(4):
        y = 100 + i * 60
        lb = [60, y, 280, y + 20]
        rb = [320, y, 540, y + 20]
        boxes.extend([lb, rb])
        names[id(lb)] = f"left{i}"
        names[id(rb)] = f"right{i}"
    return boxes, names


def test_gutter_detected():
    boxes, _ = _two_col_boxes()
    mid = page_gutter_mid(boxes)
    assert mid is not None
    assert 295 <= mid <= 305  # 栏距中点约 300


def test_left_column_read_before_right():
    boxes, names = _two_col_boxes()
    rank = reading_order_rank(boxes, fitz.Rect(0, 0, 600, 800))
    ordered = sorted(boxes, key=lambda b: rank[id(b)])
    order = [names[id(b)] for b in ordered]
    assert order[0] == "title"
    assert order.index("left0") < order.index("right0")
    assert order.index("left3") < order.index("right0")  # 左栏读完才读右栏


def test_single_column_global_order():
    boxes = [[40, 50, 300, 70], [40, 90, 300, 110], [40, 130, 300, 150], [40, 170, 300, 190]]
    assert page_gutter_mid(boxes) is None  # 单栏无栏距
    rank = reading_order_rank(boxes, fitz.Rect(0, 0, 400, 400))
    ordered = sorted(boxes, key=lambda b: rank[id(b)])
    assert ordered[0][1] == 50  # 第一块 (y50)


def test_full_width_first_then_columns():
    """通栏 (图/标题) 先, 然后全部左栏, 再全部右栏 (用户期望的"先左后右")."""
    boxes = []
    names = {}
    for i in range(3):
        tb = [60, 50 + i * 25, 280, 70 + i * 25]
        rb = [320, 50 + i * 25, 540, 70 + i * 25]
        boxes.extend([tb, rb])
        names[id(tb)] = f"col0_t{i}"
        names[id(rb)] = f"col1_t{i}"
    fig = [90, 150, 500, 250]  # 通栏图
    boxes.append(fig)
    names[id(fig)] = "figure"
    for i in range(3):
        tb = [60, 300 + i * 25, 280, 320 + i * 25]
        rb = [320, 300 + i * 25, 540, 320 + i * 25]
        boxes.extend([tb, rb])
        names[id(tb)] = f"col0_b{i}"
        names[id(rb)] = f"col1_b{i}"
    rank = reading_order_rank(boxes, fitz.Rect(0, 0, 600, 800))
    ordered = sorted(boxes, key=lambda b: rank[id(b)])
    order = [names[id(b)] for b in ordered]
    # 通栏图先 → 全部左栏 → 全部右栏
    assert order[0] == "figure"
    assert order.index("col0_t2") < order.index("col1_t0")  # 左栏全读完才右栏
    assert order.index("col0_b2") < order.index("col1_t0")
    assert order.index("col1_b2") > order.index("col1_t0")
