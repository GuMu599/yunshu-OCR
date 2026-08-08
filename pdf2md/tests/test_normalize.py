"""输出规范契约测试 — docs/PDF转Markdown零token工具实现计划.md §1"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md import normalize  # noqa: E402


def _item(md: str, itype: str = "text"):
    return {"type": itype, "markdown": md, "text": md}


def test_page_markers_and_metadata():
    meta = {"title": "T", "authors": "A", "year": "2001"}
    pages = [{"page": 1, "items": [_item("body")]}]
    out = normalize.build_markdown(meta, pages)
    assert "> **元数据块**" in out
    assert "> - 标题：T" in out
    assert "> - 年份：2001" in out
    assert "## Page 1" in out


def test_formula_code_block():
    pages = [{"page": 1, "items": [_item(r"E = mc^2", "formula")]}]
    out = normalize.build_markdown({}, pages)
    assert "```latex\nE = mc^2\n```" in out


def test_header_footer_markers():
    pages = [{"page": 1, "items": [_item("Running", "header"), _item("Page 1", "footer")]}]
    out = normalize.build_markdown({}, pages)
    assert "<!-- header -->\nRunning\n<!-- /header -->" in out
    assert "<!-- footer -->\nPage 1\n<!-- /footer -->" in out


def test_image_relative_link():
    pages = [{"page": 1, "items": [_item("![figure](images/p1.png)", "image")]}]
    out = normalize.build_markdown({}, pages)
    assert "![figure](images/p1.png)" in out


def test_blank_line_collapse():
    pages = [{"page": 1, "items": [_item("a"), _item("b")]}]
    out = normalize.build_markdown({}, pages)
    assert "\n\n\n" not in out
