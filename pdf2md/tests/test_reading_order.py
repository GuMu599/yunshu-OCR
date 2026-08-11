"""版面阅读顺序: 栏距检测 + 块级栏感知重排 (直接构造 [x0,y0,x1,y1] box, 隔离 PyMuPDF 行为)"""

import sys
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import fitz

from pdf2md.reading_order import page_gutter_mid, reading_order_rank  # noqa: E402
from pdf2md.order import order_page_elements  # noqa: E402
from pdf2md.text import region_text_ordered, region_text_ordered_excluding  # noqa: E402


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


def test_full_width_region_is_interleaved_by_vertical_position():
    """A full-width figure separates the column bands above and below it."""
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
    assert order.index("col0_t2") < order.index("col1_t0")
    assert order.index("col1_t2") < order.index("figure")
    assert order.index("figure") < order.index("col0_b0")
    assert order.index("col0_b2") < order.index("col1_b0")


def test_cross_column_region_keeps_native_line_order():
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((80, 100), "Author One, Author Two", fontsize=12)
    page.insert_text((80, 130), "Affiliation and abstract label", fontsize=10)
    assert region_text_ordered(page, [40, 80, 560, 160], gutter_mid=300).splitlines()[0].startswith("Author")
    doc.close()


def test_visual_line_keeps_superscript_between_surrounding_text():
    """Different font metrics on one visual line must not move a superscript first."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((80, 100), "Graphene sp", fontsize=12)
    page.insert_text((147, 94), "2", fontsize=7)
    page.insert_text((153, 100), " hybridized layer", fontsize=12)

    text = region_text_ordered(page, [40, 70, 300, 120])

    assert re.sub(r"\s+", "", text) == "Graphenesp2hybridizedlayer"
    doc.close()


def test_visual_line_preserves_significant_horizontal_gap():
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text((80, 100), "1", fontsize=12)
    page.insert_text((110, 100), "Results", fontsize=12)

    text = region_text_ordered(page, [40, 70, 240, 120])

    assert text == "1 Results"
    doc.close()


def test_formula_cleanup_does_not_keep_characters_outside_source_region():
    doc = fitz.open()
    page = doc.new_page(width=500, height=700)
    page.insert_text((80, 100), "preceding prose", fontsize=12)
    page.insert_text((80, 140), "x = y", fontsize=12)

    result = region_text_ordered_excluding(
        page,
        [60, 100, 300, 155],
        [[60, 115, 250, 150]],
    )

    assert result is not None
    text, excluded_chars = result
    assert text == ""
    assert excluded_chars == len("x=y")
    doc.close()


def test_caption_below_full_width_figure_precedes_following_two_column_band():
    """A centered caption belongs to its nearby full-width figure, not the right column."""
    items = [
        {"type": "image", "bbox_pdf": [70, 100, 530, 180], "text": "figure"},
        {"type": "text", "bbox_pdf": [185, 186, 425, 202], "text": "Scheme 1 caption"},
        {"type": "text", "bbox_pdf": [70, 220, 180, 240], "text": "2 Results"},
        {"type": "text", "bbox_pdf": [70, 250, 250, 270], "text": "2.1 Yield"},
        {"type": "text", "bbox_pdf": [70, 280, 280, 500], "text": "left body"},
        {"type": "image", "bbox_pdf": [330, 280, 520, 420], "text": "right figure"},
    ]

    ordered = order_page_elements(items, page_width=600, gutter_mid=300)

    assert [item["text"] for item in ordered[:4]] == [
        "figure", "Scheme 1 caption", "2 Results", "2.1 Yield",
    ]


def test_side_by_side_figures_keep_each_caption_with_its_column():
    items = [
        {"type": "image", "bbox_pdf": [70, 100, 270, 200], "text": "left figure"},
        {"type": "text", "bbox_pdf": [70, 205, 270, 225], "text": "left caption"},
        {"type": "image", "bbox_pdf": [330, 100, 530, 200], "text": "right figure"},
        {"type": "text", "bbox_pdf": [330, 205, 530, 225], "text": "right caption"},
        {"type": "text", "bbox_pdf": [70, 240, 530, 300], "text": "full-width body"},
    ]

    ordered = order_page_elements(items, page_width=600, gutter_mid=300)

    assert [item["text"] for item in ordered[:4]] == [
        "left figure", "left caption", "right figure", "right caption",
    ]


def test_section_heading_ends_local_two_column_figure_band():
    items = [
        {"type": "image", "bbox_pdf": [70, 100, 270, 200], "text": "left figure"},
        {"type": "text", "bbox_pdf": [70, 205, 270, 225], "text": "left caption"},
        {"type": "image", "bbox_pdf": [330, 100, 530, 200], "text": "right figure"},
        {"type": "text", "bbox_pdf": [330, 205, 530, 225], "text": "right caption"},
        {"type": "text", "bbox_pdf": [70, 232, 210, 248], "text": "2.3 Analysis"},
        {"type": "text", "bbox_pdf": [70, 252, 530, 330], "text": "full-width body"},
    ]

    ordered = order_page_elements(items, page_width=600, gutter_mid=300)

    assert [item["text"] for item in ordered] == [
        "left figure", "left caption", "right figure", "right caption",
        "2.3 Analysis", "full-width body",
    ]


def test_front_page_content_types_do_not_override_geometry():
    items = [
        {"type": "text", "content_type": "BODY", "bbox_pdf": [180, 30, 420, 55], "text": "Journal header"},
        {"type": "text", "content_type": "TITLE", "bbox_pdf": [100, 100, 500, 130], "text": "Title"},
        {"type": "text", "content_type": "BODY", "bbox_pdf": [80, 160, 520, 260], "text": "Abstract"},
        {"type": "text", "content_type": "H2", "bbox_pdf": [80, 300, 220, 320], "text": "Section"},
        {"type": "text", "content_type": "AUTHOR", "bbox_pdf": [80, 700, 520, 760], "text": "Footnote"},
    ]

    ordered = order_page_elements(items, page_width=600, gutter_mid=None)

    assert [item["text"] for item in ordered] == ["Journal header", "Title", "Abstract", "Section", "Footnote"]
