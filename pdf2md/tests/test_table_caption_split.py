"""Native table captions define logical boundaries inside broad detector boxes."""

import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md.table_detect import split_table_region_by_captions  # noqa: E402


def test_one_detector_container_splits_at_second_table_caption():
    doc = fitz.open()
    page = doc.new_page(width=300, height=400)
    page.insert_text((20, 40), "Table 1 First")
    page.insert_text((20, 100), "row 1")
    page.insert_text((20, 200), "Table 2 Second")
    page.insert_text((20, 260), "row 2")

    pieces = split_table_region_by_captions(page, [10, 20, 290, 300])

    assert len(pieces) == 2
    assert pieces[0][3] <= pieces[1][1]


def test_single_caption_keeps_original_region():
    doc = fitz.open()
    page = doc.new_page(width=300, height=400)
    page.insert_text((20, 40), "Table 1 Only")

    assert split_table_region_by_captions(page, [10, 20, 290, 300]) == [
        [10.0, 20.0, 290.0, 300.0]
    ]
