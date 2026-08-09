"""ocr_region_with_boxes: 像素→PDF 坐标换算 + ocr_region 重构不回归"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import numpy as np

from pdf2md import ocr as ocr_mod


class _FakeOutput:
    def __init__(self, txts, boxes, scores):
        self.txts = txts
        self.boxes = boxes
        self.scores = scores


class _FakeEngine:
    def __init__(self, txts, boxes, scores):
        self._txts = txts
        self._boxes = boxes
        self._scores = scores

    def __call__(self, png):
        return _FakeOutput(self._txts, self._boxes, self._scores)


def _fake_engine(txts, boxes, scores):
    return _FakeEngine(tuple(txts), np.asarray(boxes, dtype=np.int32), tuple(float(s) for s in scores))


def test_box_px_to_pdf():
    import fitz

    rect_tl = fitz.Point(100, 200)
    box = [[0, 0], [10, 0], [10, 10], [0, 10]]
    assert ocr_mod._box_px_to_pdf(box, rect_tl, 2.0) == (100.0, 200.0, 105.0, 205.0)


def test_ocr_region_with_boxes_converts_coords(monkeypatch):
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    rect = [100, 200, 300, 400]
    engine = _fake_engine(
        ["hello", "world"],
        [
            [[0, 0], [20, 0], [20, 10], [0, 10]],
            [[40, 20], [90, 20], [90, 30], [40, 30]],
        ],
        [0.95, 0.80],
    )
    monkeypatch.setattr(ocr_mod, "_get_engine", lambda: engine)
    lines = ocr_mod.ocr_region_with_boxes(page, rect, dpi=144)  # scale 2
    assert len(lines) == 2
    assert lines[0].text == "hello"
    assert lines[0].box_pdf == (100.0, 200.0, 110.0, 205.0)
    assert lines[0].confidence == 0.95
    assert lines[1].box_pdf == (120.0, 210.0, 145.0, 215.0)


def test_ocr_region_refactor_keeps_behavior(monkeypatch):
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    rect = [0, 0, 100, 100]
    engine = _fake_engine(
        [" a ", "b"],
        [
            [[0, 0], [10, 0], [10, 10], [0, 10]],
            [[0, 20], [10, 20], [10, 30], [0, 30]],
        ],
        [0.9, 0.8],
    )
    monkeypatch.setattr(ocr_mod, "_get_engine", lambda: engine)
    assert ocr_mod.ocr_region(page, rect, dpi=72) == [("a", 0.9), ("b", 0.8)]


def test_ocr_region_empty_rect():
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    assert ocr_mod.ocr_region_with_boxes(page, [9999, 9999, 9999, 9999], dpi=72) == []
