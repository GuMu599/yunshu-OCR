"""Preflight exposes all local model dependencies without downloading them."""

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md.pipeline import preflight  # noqa: E402


def test_preflight_reports_layout_ocr_and_table_components(tmp_path, monkeypatch):
    model = tmp_path / "layout.pt"
    model.write_bytes(b"weights")
    monkeypatch.setattr("pdf2md.ocr.adapter_status", lambda: {"available": True, "path": "ocr"})
    monkeypatch.setattr("pdf2md.table_model.adapter_status", lambda: {"available": False, "path": "table", "error": "missing"})

    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    result = preflight(
        model, layout_model_sha256=digest, use_table_model=True, do_ocr=True
    )

    assert result["layout"]["available"] is True
    assert result["ocr"]["available"] is True
    assert result["table"]["available"] is False
    assert "table" in result["warnings"]


def test_strict_preflight_requires_every_enabled_model(monkeypatch):
    monkeypatch.setattr(
        "pdf2md.layout.preflight_layout_model",
        lambda *args, **kwargs: {"available": True, "path": "layout"},
    )
    monkeypatch.setattr(
        "pdf2md.ocr.adapter_status",
        lambda: {"available": False, "error": "missing OCR"},
    )
    monkeypatch.setattr(
        "pdf2md.table_model.adapter_status",
        lambda: {"available": False, "error": "missing table"},
    )
    monkeypatch.setattr(
        "pdf2md.formulas.FormulaModel.checkpoint_status",
        lambda: {"available": False, "error": "missing formula"},
    )

    with pytest.raises(RuntimeError, match=r"ocr,table,formula.*pdf2md\.models install"):
        preflight(strict=True)


def test_strict_preflight_allows_explicitly_disabled_models(monkeypatch):
    monkeypatch.setattr(
        "pdf2md.layout.preflight_layout_model",
        lambda *args, **kwargs: {"available": True, "path": "layout"},
    )

    result = preflight(
        do_ocr=False,
        use_table_model=False,
        formula_engine="rapidocr",
        strict=True,
    )

    assert result["ocr"]["disabled"] is True
    assert result["table"]["disabled"] is True
    assert result["formula"]["disabled"] is True
