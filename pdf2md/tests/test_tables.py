"""表格判别逻辑测试"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md import tables  # noqa: E402


def test_prose_not_table_data():
    assert tables.looks_like_table_data("This is a long sentence that goes on and on across the page like normal prose text.") is False


def test_short_rows_look_like_table_data():
    raw = "1 0.5 0.5 0.5\n2 0.25 0.75 0.5\n3 0.1 0.9 0.5\n4 0.8 0.2 0.5"
    assert tables.looks_like_table_data(raw) is True


def test_few_lines_not_table():
    assert tables.looks_like_table_data("a\nb") is False


def test_empty_not_table():
    assert tables.looks_like_table_data("") is False
