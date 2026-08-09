"""跨页续表合并"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md.pipeline import _merge_cross_page_tables  # noqa: E402
from pdf2md.table_html import make_table, parse_html_table, table_to_html  # noqa: E402
from pdf2md.tables import merge_table_items  # noqa: E402


def _item(html, bbox):
    return {"type": "table", "bbox_pdf": bbox, "html": html}


def test_merge_table_items_drop_duplicate_header():
    a = _item(table_to_html(make_table([["H1", "H2"], ["1", "a"], ["2", "b"]])), [0, 0, 0, 0])
    b = _item(table_to_html(make_table([["H1", "H2"], ["3", "c"], ["4", "d"]])), [0, 0, 0, 0])
    m = merge_table_items(a, b)
    assert m is not None
    assert m["source"] == "merged_cross_page"
    merged = parse_html_table(m["html"])
    assert merged.rows == 5  # 表头去重: 3+3-1
    assert merged.text_at(3, 0) == "3"
    assert merged.text_at(4, 1) == "d"


def test_merge_table_items_keep_all_when_no_repeat_header():
    a = _item(table_to_html(make_table([["H1", "H2"], ["1", "a"]])), [0, 0, 0, 0])
    b = _item(table_to_html(make_table([["2", "b"], ["3", "c"]])), [0, 0, 0, 0])
    m = merge_table_items(a, b)
    assert m is not None
    merged = parse_html_table(m["html"])
    assert merged.rows == 4  # 无重复表头 → 全部保留


def test_merge_table_items_rejects_col_mismatch():
    a = _item(table_to_html(make_table([["H1", "H2"], ["1", "a"]])), [0, 0, 0, 0])
    b = _item(table_to_html(make_table([["H1", "H2", "H3"], ["1", "a", "x"]])), [0, 0, 0, 0])
    assert merge_table_items(a, b) is None


def test_merge_table_items_requires_html():
    a = {"type": "table", "markdown": "| a |\n| --- |\n| 1 |", "html": None}
    b = _item(table_to_html(make_table([["b"]])), [0, 0, 0, 0])
    assert merge_table_items(a, b) is None


def test_pipeline_merge_helper():
    pages = [
        [_item(table_to_html(make_table([["H1", "H2"], ["1", "a"]])), [0, 700, 100, 790])],
        [_item(table_to_html(make_table([["H1", "H2"], ["2", "b"]])), [0, 10, 100, 90])],
    ]
    n = _merge_cross_page_tables(pages, {1: 800, 2: 800})
    assert n == 1
    assert len(pages[1]) == 0  # 后页表格被并入
    assert pages[0][0]["source"] == "merged_cross_page"


def test_pipeline_merge_helper_not_triggered_when_not_anchored():
    # 后页表格不在页顶 → 不合并
    pages = [
        [_item(table_to_html(make_table([["H1", "H2"], ["1", "a"]])), [0, 700, 100, 790])],
        [_item(table_to_html(make_table([["H1", "H2"], ["2", "b"]])), [0, 400, 100, 490])],
    ]
    n = _merge_cross_page_tables(pages, {1: 800, 2: 800})
    assert n == 0
    assert len(pages[1]) == 1
