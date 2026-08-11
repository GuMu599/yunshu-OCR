"""Overlapping detector regions must not duplicate the same content."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md.layout import suppress_overlapping_regions  # noqa: E402


def test_overlapping_text_and_title_regions_are_suppressed():
    regions = [
        {"visual_class": "text", "bbox_pdf": [20, 50, 480, 120], "confidence": 0.72},
        {"visual_class": "title", "bbox_pdf": [18, 48, 482, 122], "confidence": 0.88},
    ]

    out = suppress_overlapping_regions(regions)

    assert len(out) == 1
    assert out[0]["visual_class"] == "title"
    assert set(out[0]["merged_detector_classes"]) == {"text", "title"}


def test_non_overlapping_regions_are_preserved():
    regions = [
        {"visual_class": "text", "bbox_pdf": [20, 50, 480, 100], "confidence": 0.7},
        {"visual_class": "text", "bbox_pdf": [20, 130, 480, 180], "confidence": 0.8},
    ]
    assert len(suppress_overlapping_regions(regions)) == 2


def test_broad_text_container_does_not_replace_local_column_regions():
    regions = [
        {"visual_class": "text", "bbox_pdf": [20, 20, 580, 760], "confidence": 0.95},
        {"visual_class": "text", "bbox_pdf": [30, 30, 275, 350], "confidence": 0.8},
        {"visual_class": "text", "bbox_pdf": [305, 30, 550, 350], "confidence": 0.8},
        {"visual_class": "text", "bbox_pdf": [30, 380, 275, 730], "confidence": 0.8},
        {"visual_class": "text", "bbox_pdf": [305, 380, 550, 730], "confidence": 0.8},
    ]

    out = suppress_overlapping_regions(regions)

    assert len(out) == 4
    assert all(region["bbox_pdf"] != [20, 20, 580, 760] for region in out)


def test_stacked_formula_container_replaces_overlapping_fragments():
    regions = [
        {"visual_class": "formula", "bbox_pdf": [80, 100, 520, 220], "confidence": 0.74},
        {"visual_class": "formula", "bbox_pdf": [82, 101, 518, 170], "confidence": 0.61},
        {"visual_class": "formula", "bbox_pdf": [85, 185, 515, 218], "confidence": 0.59},
    ]

    out = suppress_overlapping_regions(regions)

    assert len(out) == 1
    assert out[0]["bbox_pdf"] == [80, 100, 520, 220]
