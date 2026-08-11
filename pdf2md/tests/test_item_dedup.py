"""Extracted items are deduplicated after all detector branches have run."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md.pipeline import _deduplicate_page_items  # noqa: E402


def test_duplicate_text_from_overlapping_regions_is_removed():
    items = [
        {"id": "a", "type": "text", "bbox_pdf": [10, 10, 300, 80], "text": "same paragraph text", "markdown": "same paragraph text"},
        {"id": "b", "type": "text", "bbox_pdf": [12, 12, 302, 82], "text": "same paragraph text", "markdown": "same paragraph text"},
    ]
    out, removed = _deduplicate_page_items(items)
    assert len(out) == 1
    assert removed == 1


def test_caption_and_image_are_not_deduplicated():
    items = [
        {"id": "image", "type": "image", "bbox_pdf": [10, 10, 300, 180], "text": "", "markdown": "![figure](x.png)"},
        {"id": "caption", "type": "text", "bbox_pdf": [10, 185, 300, 205], "text": "Fig. 1 result", "markdown": "Fig. 1 result"},
    ]
    out, removed = _deduplicate_page_items(items)
    assert len(out) == 2
    assert removed == 0


def test_same_height_text_in_opposite_columns_is_preserved():
    items = [
        {"id": "left", "type": "text", "bbox_pdf": [10, 10, 200, 80], "text": "left column contains a shared phrase", "markdown": "left column contains a shared phrase"},
        {"id": "right", "type": "text", "bbox_pdf": [300, 10, 500, 80], "text": "right column contains a shared phrase and more", "markdown": "right column contains a shared phrase and more"},
    ]
    out, removed = _deduplicate_page_items(items)
    assert len(out) == 2
    assert removed == 0


def test_duplicate_short_formula_number_inside_broad_region_is_removed():
    items = [
        {
            "id": "label",
            "type": "text",
            "bbox_pdf": [510, 447, 527, 460],
            "text": "( 2)",
            "markdown": "( 2)",
        },
        {
            "id": "broad-candidate",
            "type": "text",
            "bbox_pdf": [149, 408, 526, 496],
            "text": "( 2)",
            "markdown": "( 2)",
        },
    ]

    out, removed = _deduplicate_page_items(items)

    assert [item["id"] for item in out] == ["label"]
    assert removed == 1
