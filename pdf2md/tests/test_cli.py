"""CLI wiring for explicit models and strict offline conversion."""

import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md import cli  # noqa: E402


def test_cli_passes_layout_model_and_offline(monkeypatch, tmp_path):
    doc = fitz.open()
    doc.new_page()
    pdf = tmp_path / "input.pdf"
    doc.save(pdf)
    doc.close()
    model = tmp_path / "layout.pt"
    model.write_bytes(b"weights")
    captured = {}

    def fake_convert(pdf_path, output_dir, **kwargs):
        captured.update(kwargs)
        return {
            "stats": {"text_regions": 0, "images": 0, "tables": 0, "table_images": 0,
                      "formulas": 0, "formula_uncertain": 0, "formula_fallback_images": 0,
                      "ocr_pages": 0},
            "elapsed_s": 0.1, "markdown_path": str(tmp_path / "out.md"),
            "meta": {}, "pdf_profile": None, "formula_detected": True, "coverage": [],
        }

    monkeypatch.setattr(cli, "convert_pdf", fake_convert)
    monkeypatch.setattr(sys, "argv", [
        "pdf2md", str(pdf), "--output", str(tmp_path / "out"),
        "--layout-model", str(model), "--layout-model-sha256", "a" * 64, "--offline",
    ])

    assert cli.main() == 0
    assert captured["layout_model_path"] == str(model)
    assert captured["layout_model_sha256"] == "a" * 64
    assert captured["offline"] is True


def test_cli_does_not_create_output_before_pipeline_preflight(monkeypatch, tmp_path):
    doc = fitz.open()
    doc.new_page()
    pdf = tmp_path / "input.pdf"
    doc.save(pdf)
    doc.close()
    output = tmp_path / "not-created"

    def fail_preflight(*args, **kwargs):
        assert not output.exists()
        raise RuntimeError("model_missing:layout")

    monkeypatch.setattr(cli, "convert_pdf", fail_preflight)
    monkeypatch.setattr(sys, "argv", [
        "pdf2md", str(pdf), "--output", str(output),
        "--layout-model", str(tmp_path / "missing.pt"),
    ])

    assert cli.main() == 1
    assert not output.exists()


def test_cli_defaults_to_offline_without_flag(monkeypatch, tmp_path):
    doc = fitz.open()
    doc.new_page()
    pdf = tmp_path / "input.pdf"
    doc.save(pdf)
    doc.close()
    captured = {}

    def fake_convert(pdf_path, output_dir, **kwargs):
        captured.update(kwargs)
        return {
            "stats": {"text_regions": 0, "images": 0, "tables": 0, "table_images": 0,
                      "formulas": 0, "formula_uncertain": 0, "formula_fallback_images": 0,
                      "ocr_pages": 0},
            "elapsed_s": 0.1, "markdown_path": str(tmp_path / "out.md"),
            "meta": {}, "pdf_profile": None, "formula_detected": True, "coverage": [],
        }

    monkeypatch.setattr(cli, "convert_pdf", fake_convert)
    monkeypatch.setattr(sys, "argv", ["pdf2md", str(pdf), "--output", str(tmp_path / "out")])

    assert cli.main() == 0
    assert captured["offline"] is True
