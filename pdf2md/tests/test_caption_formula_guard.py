"""Caption normalization is tolerant and runs before formula OCR."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md import formulas  # noqa: E402


def test_mojibake_figure_caption_is_recognized():
    assert formulas.looks_like_caption("Fig£®1 Raman spectra")
    assert formulas.caption_kind("Fig£®1 Raman spectra") == "figure"


def test_scheme_and_chinese_caption_are_recognized():
    assert formulas.caption_kind("Scheme 2. Synthesis route") == "figure"
    assert formulas.caption_kind("图 3 氧化石墨烯结构") == "figure"
    assert formulas.caption_kind("表 2 实验参数") == "table"


def test_caption_is_rejected_before_formula_recognition():
    assert formulas.is_formula_candidate("Fig£®6 XRD patterns") is False
    assert formulas.is_formula_candidate("Intensity (a.u.)") is False
    assert formulas.is_formula_candidate(r"E = mc^2") is True
