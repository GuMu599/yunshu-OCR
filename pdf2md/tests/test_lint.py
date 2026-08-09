"""lint 表格列一致性检查"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md.lint import lint_markdown  # noqa: E402


def test_table_col_mismatch_detected():
    md = "| a | b |\n| --- | --- |\n| 1 | 2 | 3 |\n"
    kinds = [i["kind"] for i in lint_markdown(md)]
    assert "table_col_mismatch" in kinds


def test_table_consistent_clean():
    md = "| a | b |\n| --- | --- |\n| 1 | 2 |\n"
    assert lint_markdown(md) == []


def test_marker_comment_not_flagged():
    md = "<!-- table: full structure in layout.json -->\n| a | b |\n| --- | --- |\n| 1 | 2 |\n"
    assert lint_markdown(md) == []


def test_existing_checks_still_work():
    md = "## 1.1 2.2 First\n\n```latex\n(a) x = 1 (1.1)\n(b) y = 2 (1.2)\n```\n"
    kinds = {i["kind"] for i in lint_markdown(md)}
    assert "heading_toc_merge" in kinds
    assert "formula_merged" in kinds
