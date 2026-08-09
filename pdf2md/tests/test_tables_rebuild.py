"""几何重建: 合成 PDF → 词级坐标 → Table"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import fitz

from pdf2md.tables import native_word_items, rebuild_table_from_boxes  # noqa: E402


def _page(cells, cols_x, rows_y, fontsize=10):
    """cells 中 None 表示空格 (不插入文字)."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    for ri, rowvals in enumerate(cells):
        y = rows_y[ri]
        for ci, val in enumerate(rowvals):
            if val is None:
                continue
            page.insert_text(fitz.Point(cols_x[ci], y), val, fontsize=fontsize)
    return page


def _rebuild(page, rect=(0, 0, 400, 400)):
    return rebuild_table_from_boxes(native_word_items(page, rect))


def test_basic_grid():
    cells = [["H1", "H2", "H3"], ["a1", "a2", "a3"], ["b1", "b2", "b3"]]
    page = _page(cells, [50, 150, 250], [50, 70, 90])
    t = _rebuild(page)
    assert t is not None
    assert (t.rows, t.cols) == (3, 3)
    assert t.text_at(0, 0) == "H1"
    assert t.text_at(1, 1) == "a2"
    assert t.text_at(2, 2) == "b3"


def test_right_aligned_numeric_column():
    f = fitz.Font("helv")
    cells = [["Metric", "Value"], ["alpha", "1"], ["beta", "123"], ["gamma", "10"]]
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    left = 60
    right = 250
    ys = [40, 60, 80, 100]
    for ri, (m, v) in enumerate(cells):
        y = ys[ri]
        page.insert_text(fitz.Point(left, y), m, fontsize=10)
        w = f.text_length(v, fontsize=10)
        page.insert_text(fitz.Point(right - w, y), v, fontsize=10)
    t = rebuild_table_from_boxes(native_word_items(page, (0, 0, 400, 400)))
    assert t is not None
    assert t.cols == 2
    assert t.text_at(1, 0) == "alpha"
    assert t.text_at(1, 1) == "1"
    assert t.text_at(3, 1) == "10"
    assert t.align[1] == "right"


def test_multiline_cell_merged():
    # 左列 data 是两行换行 (第二行紧贴第一行下方), 右列对齐首行 → 合并成一个逻辑行
    page = _page(
        [["header", "H2", "H3"], ["long1", "x", "y"]],
        [50, 150, 250],
        [40, 58],
    )
    page.insert_text(fitz.Point(50, 72), "long2", fontsize=10)  # 换行第二行
    t = _rebuild(page)
    assert t is not None
    assert t.rows == 2
    assert t.text_at(1, 0) == "long1 long2"
    assert t.text_at(1, 1) == "x"
    assert t.text_at(1, 2) == "y"


def test_empty_cell_and_ragged():
    cells = [["H1", "H2"], ["a1", None], ["b1", "b2"]]
    page = _page(cells, [50, 150], [50, 70, 90])
    t = _rebuild(page)
    assert t is not None
    assert t.cols == 2
    assert t.text_at(1, 0) == "a1"
    assert t.text_at(1, 1) == ""
    assert t.text_at(2, 1) == "b2"


def test_single_row_not_table():
    # 一行内多个词 → 仅 1 行 → 退化, 返回 None
    page = _page([["a", "b", "c", "d"]], [50, 100, 150, 200], [50])
    assert _rebuild(page) is None


def test_too_few_words():
    page = _page([["a", "b"]], [50, 150], [50, 70])
    assert _rebuild(page) is None


def test_prose_not_table():
    # 散文段落: 每行词区间连续重叠 → 单列, 退化
    lines = [
        "This is a long sentence that goes on and on across the page",
        "like normal prose text that fills a whole paragraph of words",
        "that just keeps flowing until the line reaches the right margin",
    ]
    doc = fitz.open()
    page = doc.new_page(width=500, height=300)
    for i, line in enumerate(lines):
        page.insert_text(fitz.Point(40, 50 + i * 15), line, fontsize=10)
    assert _rebuild(page, (0, 0, 500, 300)) is None
