"""Table / HTML / Markdown 互转测试"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md.table_html import (  # noqa: E402
    MERGE_BLANK,
    MERGE_EXPAND,
    make_table,
    parse_html_table,
    table_to_html,
    table_to_md,
)


def _table():
    return make_table(
        [
            ["h1", "h2"],
            ["a", "b"],
            ["c", "d"],
        ]
    )


def test_make_table_and_md():
    md = table_to_md(_table())
    assert md is not None
    lines = md.splitlines()
    assert lines[0] == "| h1 | h2 |"
    assert lines[1] == "| --- | --- |"
    assert lines[2] == "| a | b |"
    assert lines[3] == "| c | d |"


def test_md_escape_pipe():
    t = make_table([["a|b", "x"], ["c", "d"]])
    lines = table_to_md(t).splitlines()
    assert lines[0] == "| a\\|b | x |"


def test_md_multiline_cell_br():
    t = make_table([["h", "v"], ["line1\nline2", "z"]])
    lines = table_to_md(t).splitlines()
    assert lines[2] == "| line1<br>line2 | z |"


def test_md_right_align_separator():
    t = make_table([["h", "n"], ["x", "1"], ["y", "2"]])
    t.align = [None, "right"]
    lines = table_to_md(t).splitlines()
    assert lines[1] == "| --- | ---: |"


def test_parse_html_flat():
    html = "<table><tr><td>h1</td><td>h2</td></tr><tr><td>a</td><td>b</td></tr></table>"
    t = parse_html_table(html)
    assert t is not None
    assert (t.rows, t.cols) == (2, 2)
    assert t.text_at(1, 0) == "a"
    assert t.text_at(1, 1) == "b"


def test_parse_html_sections_and_entities():
    html = (
        "<table><thead><tr><th>H</th></tr></thead>"
        "<tbody><tr><td>a &amp; b</td></tr></tbody></table>"
    )
    t = parse_html_table(html)
    assert t is not None
    assert t.rows == 2
    assert t.text_at(0, 0) == "H"
    assert t.text_at(1, 0) == "a & b"


def test_parse_html_rowspan_colspan():
    html = (
        "<table>"
        "<tr><td rowspan=\"2\">m</td><td>a</td><td colspan=\"2\">b</td></tr>"
        "<tr><td>c</td><td>d</td><td>e</td></tr>"
        "</table>"
    )
    t = parse_html_table(html)
    assert t is not None
    assert (t.rows, t.cols) == (2, 4)
    cell = t.cell(1, 0)
    assert cell is not None
    assert (cell.rowspan, cell.colspan) == (2, 1)
    assert t.text_at(1, 0) == "m"  # rowspan 扩展
    assert t.text_at(0, 2) == "b"
    assert t.text_at(0, 3) == "b"  # colspan 扩展


def test_parse_html_malformed_tolerant():
    # 缺 </table>、非法 colspan、无 table 标签 → 不抛错
    assert parse_html_table("not a table") is None
    t = parse_html_table('<table><tr><td colspan="x">a</td></tr></table')
    assert t is not None
    assert t.cols == 1


def test_merge_policies():
    html = (
        "<table>"
        "<tr><td rowspan=\"2\">m</td><td>a</td></tr>"
        "<tr><td>b</td></tr>"
        "</table>"
    )
    t = parse_html_table(html)
    md_expand = table_to_md(t, MERGE_EXPAND)
    md_blank = table_to_md(t, MERGE_BLANK)
    assert md_expand.splitlines()[2] == "| m | b |"  # rowspan 展开复制
    assert md_blank.splitlines()[2] == "|  | b |"    # rowspan 空白占位


def test_html_roundtrip():
    html = (
        "<table>"
        "<tr><td rowspan=\"2\">m</td><td>a</td><td colspan=\"2\">b</td></tr>"
        "<tr><td>c</td><td>d</td><td>e</td></tr>"
        "</table>"
    )
    t = parse_html_table(html)
    assert t is not None
    t2 = parse_html_table(table_to_html(t))
    assert t2 is not None
    assert t2.expanded() == t.expanded()
    # 无损 HTML 保留 span
    assert 'rowspan="2"' in table_to_html(t)
    assert 'colspan="2"' in table_to_html(t)


def test_parse_html_empty_trailing_row_dropped():
    html = "<table><tr><td>a</td></tr><tr></tr><tr></tr></table>"
    t = parse_html_table(html)
    assert t is not None
    assert t.rows == 1


def test_degenerate_table_none():
    assert table_to_md(make_table([])) is None
    t = make_table([["", ""], ["", ""]])
    assert table_to_md(t) is not None  # 空但结构合法的表格仍输出
