"""Untrusted documents are constrained before expensive rendering and inference."""

import subprocess
import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md.resources import ConversionLimits, ResourceLimitError, run_bounded_process  # noqa: E402
from pdf2md import pipeline  # noqa: E402


def _pdf(path: Path, *, width: float = 600, height: float = 800, pages: int = 1) -> Path:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=width, height=height)
    doc.save(path)
    doc.close()
    return path


def test_input_file_size_limit_is_enforced_before_conversion(tmp_path):
    pdf = _pdf(tmp_path / "input.pdf")
    limits = ConversionLimits(max_input_bytes=pdf.stat().st_size - 1)
    with pytest.raises(ResourceLimitError, match="input_bytes"):
        limits.validate_input(pdf, dpi=220, image_dpi=200, formula_dpi=300)


def test_page_pixel_budget_rejects_giant_render(tmp_path):
    pdf = _pdf(tmp_path / "giant.pdf", width=4000, height=4000)
    limits = ConversionLimits(max_page_pixels=1_000_000)
    with pytest.raises(ResourceLimitError, match="page_pixels"):
        limits.validate_input(pdf, dpi=220, image_dpi=200, formula_dpi=300)


def test_invalid_dpi_and_page_count_are_rejected(tmp_path):
    pdf = _pdf(tmp_path / "input.pdf")
    limits = ConversionLimits()
    with pytest.raises(ResourceLimitError, match="dpi"):
        limits.validate_input(pdf, dpi=0, image_dpi=200, formula_dpi=300)
    with pytest.raises(ResourceLimitError, match="max_pages"):
        limits.validate_input(pdf, dpi=220, image_dpi=200, formula_dpi=300, max_pages=0)


def test_worker_timeout_terminates_untrusted_process(tmp_path):
    limits = ConversionLimits(max_runtime_seconds=0.1, max_ram_bytes=512 * 1024**2)
    with pytest.raises(ResourceLimitError, match="runtime_seconds"):
        run_bounded_process(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            limits=limits,
            output_dir=tmp_path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def test_convert_pdf_uses_process_isolation_by_default(monkeypatch, tmp_path):
    pdf = _pdf(tmp_path / "input.pdf")
    captured = {}

    def fake_isolated(payload, limits):
        captured["payload"] = payload
        captured["limits"] = limits
        return {"sentinel": "isolated"}

    monkeypatch.setattr(pipeline, "run_isolated_conversion", fake_isolated)
    report = pipeline.convert_pdf(str(pdf), str(tmp_path / "out"), do_ocr=False)

    assert report == {"sentinel": "isolated"}
    assert captured["payload"]["pdf_path"] == str(pdf)
    assert isinstance(captured["limits"], ConversionLimits)


def test_inprocess_worker_enforces_detector_region_limit(monkeypatch, tmp_path):
    pdf = _pdf(tmp_path / "input.pdf")
    regions = [
        {"page": 1, "bbox_pdf": [0, 0, 10, 10], "visual_class": "artifact", "confidence": 1.0},
        {"page": 1, "bbox_pdf": [20, 20, 30, 30], "visual_class": "artifact", "confidence": 1.0},
    ]
    monkeypatch.setattr(pipeline.layout_mod, "detect_layout", lambda *args, **kwargs: [regions])
    limits = ConversionLimits(max_regions_per_page=1)

    with pytest.raises(ResourceLimitError, match="resource_limit:regions"):
        pipeline.convert_pdf(
            str(pdf), str(tmp_path / "out"), do_ocr=False, use_table_model=False,
            isolate=False, resource_limits=limits,
        )
