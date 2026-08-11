"""YOLO 表格区域合并"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md.layout import merge_table_regions  # noqa: E402


def _t(bbox, conf=0.5):
    return {"visual_class": "table", "bbox_pdf": bbox, "confidence": conf}


def test_merge_overlapping_tables():
    regions = [_t([0, 0, 100, 100], 0.5), _t([50, 50, 150, 150], 0.6), {"visual_class": "text", "bbox_pdf": [0, 200, 100, 220], "confidence": 0.7}]
    out = merge_table_regions(regions)
    tables = [r for r in out if r["visual_class"] == "table"]
    assert len(tables) == 1
    assert tables[0]["bbox_pdf"] == [0, 0, 150, 150]
    assert tables[0]["confidence"] == 0.6
    assert len([r for r in out if r["visual_class"] == "text"]) == 1


def test_vertical_adjacent_tables_remain_independent():
    regions = [_t([0, 0, 100, 50]), _t([10, 55, 110, 120])]
    out = merge_table_regions(regions)
    assert len([r for r in out if r["visual_class"] == "table"]) == 2


def test_broad_container_does_not_merge_two_precise_tables():
    regions = [
        _t([0, 0, 100, 220], 0.5),
        _t([0, 5, 100, 100], 0.7),
        _t([0, 115, 100, 215], 0.8),
    ]
    out = merge_table_regions(regions)
    tables = [r for r in out if r["visual_class"] == "table"]
    assert [table["bbox_pdf"] for table in tables] == [
        [0, 5, 100, 100],
        [0, 115, 100, 215],
    ]


def test_far_tables_not_merged():
    regions = [_t([0, 0, 100, 50]), _t([10, 200, 110, 300])]
    out = merge_table_regions(regions)
    assert len([r for r in out if r["visual_class"] == "table"]) == 2


def test_horizontal_only_no_merge():
    # 水平分离 (无水平重叠) → 不合并
    regions = [_t([0, 0, 50, 100]), _t([200, 0, 300, 100])]
    out = merge_table_regions(regions)
    assert len([r for r in out if r["visual_class"] == "table"]) == 2
