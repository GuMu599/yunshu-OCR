"""Pipeline-level regression contracts for evidence-based conversion."""

import io
import sys
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md import pipeline  # noqa: E402


def _chart_png() -> bytes:
    image = Image.new("RGB", (400, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.line((10, 160, 380, 20), fill="black", width=4)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def test_table_labeled_scientific_visual_is_exported_as_image(monkeypatch, tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=500, height=700)
    rect = fitz.Rect(50, 100, 450, 280)
    page.insert_image(rect, stream=_chart_png())
    page.insert_text((55, 302), "Fig. 1 Raman spectra", fontsize=10)
    pdf = tmp_path / "visual.pdf"
    doc.save(pdf)
    doc.close()
    monkeypatch.setattr(
        pipeline.layout_mod,
        "detect_layout",
        lambda *a, **k: [[{"page": 1, "bbox_pdf": list(rect), "visual_class": "table", "confidence": 0.9}]],
    )

    report = pipeline.convert_pdf(
        str(pdf), str(tmp_path / "out"), do_ocr=False, use_table_model=False,
        isolate=False,
    )

    items = report["elements"][0]["items"]
    visual = next(item for item in items if item["type"] == "image")
    assert visual["detector_class"] == "table"
    assert visual["semantic_reason"] in {"raster_visual", "figure_caption"}
    assert not any(item["type"] in {"table", "table_image"} for item in items)


def test_caption_detector_region_does_not_call_formula_ocr(monkeypatch, tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=500, height=700)
    page.insert_text((50, 100), "Fig£®6 XRD patterns", fontsize=10)
    pdf = tmp_path / "caption.pdf"
    doc.save(pdf)
    doc.close()
    monkeypatch.setattr(
        pipeline.layout_mod,
        "detect_layout",
        lambda *a, **k: [[{"page": 1, "bbox_pdf": [45, 80, 300, 115], "visual_class": "formula", "confidence": 0.8}]],
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("formula OCR must be gated before invocation")

    monkeypatch.setattr(pipeline.formulas, "ocr_formula_latex", fail_if_called)
    report = pipeline.convert_pdf(str(pdf), str(tmp_path / "out"), do_ocr=False, isolate=False)

    items = report["elements"][0]["items"]
    assert any(item["type"] == "text" for item in items)
    assert not any(item["type"] == "formula" for item in items)
    assert report["stats"]["formula_rejected"] == 1


def test_missing_layout_model_fails_before_output_directory_is_created(tmp_path):
    doc = fitz.open()
    doc.new_page()
    pdf = tmp_path / "input.pdf"
    doc.save(pdf)
    doc.close()
    output = tmp_path / "not-created"

    try:
        pipeline.convert_pdf(str(pdf), str(output), layout_model_path=tmp_path / "missing.pt")
    except RuntimeError as exc:
        assert "model_missing:layout" in str(exc)
    else:
        raise AssertionError("missing layout weights must fail conversion")
    assert not output.exists()


def test_auto_formula_engine_uses_verified_model_for_one_formula():
    assert pipeline._use_formula_model("auto", detected_formulas=1) is True
    assert pipeline._use_formula_model("auto", detected_formulas=0) is False


def test_rejected_formula_candidate_is_not_counted_as_formula(monkeypatch, tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=500, height=700)
    page.insert_text((50, 100), "x = 1", fontsize=10)
    pdf = tmp_path / "formula.pdf"
    doc.save(pdf)
    doc.close()
    monkeypatch.setattr(
        pipeline.layout_mod,
        "detect_layout",
        lambda *args, **kwargs: [[{
            "page": 1, "bbox_pdf": [45, 80, 180, 115],
            "visual_class": "formula", "confidence": 0.9,
        }]],
    )
    monkeypatch.setattr(
        pipeline.formulas,
        "ocr_formula_latex",
        lambda *args, **kwargs: ("ordinary prose", 0.99, "fake"),
    )

    report = pipeline.convert_pdf(
        str(pdf), str(tmp_path / "out"), isolate=False, do_ocr=False,
    )
    assert report["stats"]["formulas"] == 0
    assert report["stats"]["formula_rejected"] == 1
    assert not any(
        item["type"] == "formula"
        for page_result in report["elements"]
        for item in page_result["items"]
    )


def test_stacked_formula_region_emits_each_equation(monkeypatch, tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=500, height=700)
    page.insert_text((100, 130), "x_i = 1", fontsize=12)
    page.insert_text((100, 165), "y_i = 2", fontsize=12)
    page.insert_text((100, 200), "z_i = 3", fontsize=12)
    pdf = tmp_path / "stacked-formulas.pdf"
    doc.save(pdf)
    doc.close()
    monkeypatch.setattr(
        pipeline.layout_mod,
        "detect_layout",
        lambda *args, **kwargs: [[{
            "page": 1,
            "bbox_pdf": [80, 105, 300, 215],
            "visual_class": "formula",
            "confidence": 0.9,
        }]],
    )

    def recognize_line(page, rect, **kwargs):
        text = page.get_textbox(fitz.Rect(*rect)).strip().replace(" ", "")
        return text, 0.8, "test"

    monkeypatch.setattr(pipeline.formulas, "ocr_formula_latex", recognize_line)

    report = pipeline.convert_pdf(
        str(pdf), str(tmp_path / "out"), isolate=False, do_ocr=False,
        formula_engine="rapidocr",
    )

    formula_items = [
        item
        for page_result in report["elements"]
        for item in page_result["items"]
        if item["type"] == "formula"
    ]
    assert len(formula_items) == 3
    assert report["stats"]["formulas"] == 3


def test_formula_native_text_container_is_not_emitted_twice(monkeypatch, tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=500, height=700)
    page.insert_text((100, 130), "x = y", fontsize=12)
    pdf = tmp_path / "formula-text-duplicate.pdf"
    doc.save(pdf)
    doc.close()
    monkeypatch.setattr(
        pipeline.layout_mod,
        "detect_layout",
        lambda *args, **kwargs: [[
            {
                "page": 1,
                "bbox_pdf": [80, 105, 300, 145],
                "visual_class": "text",
                "confidence": 0.8,
            },
            {
                "page": 1,
                "bbox_pdf": [80, 105, 300, 145],
                "visual_class": "formula",
                "confidence": 0.9,
            },
        ]],
    )
    monkeypatch.setattr(
        pipeline.formulas, "native_formula_latex", lambda raw: r"x = y" if raw else None
    )

    report = pipeline.convert_pdf(
        str(pdf), str(tmp_path / "out"), isolate=False, do_ocr=False,
        formula_engine="rapidocr",
    )

    items = report["elements"][0]["items"]
    assert [item["type"] for item in items].count("formula") == 1
    assert not any(item["type"] == "text" and "x = y" in item["text"] for item in items)
    assert report["stats"]["formula_text_duplicates_removed"] == 1
    assert report["stats"]["formula_text_duplicates_remaining"] == 0


def test_formula_overlap_removes_equation_but_keeps_adjacent_prose(monkeypatch, tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=500, height=700)
    page.insert_text((80, 100), "Equations follow:", fontsize=12)
    page.insert_text((80, 140), "x = y", fontsize=12)
    pdf = tmp_path / "mixed-formula-text.pdf"
    doc.save(pdf)
    doc.close()
    monkeypatch.setattr(
        pipeline.layout_mod,
        "detect_layout",
        lambda *args, **kwargs: [[
            {
                "page": 1,
                "bbox_pdf": [60, 75, 300, 155],
                "visual_class": "text",
                "confidence": 0.8,
            },
            {
                "page": 1,
                "bbox_pdf": [60, 115, 250, 150],
                "visual_class": "formula",
                "confidence": 0.9,
            },
        ]],
    )
    monkeypatch.setattr(
        pipeline.formulas, "native_formula_latex", lambda raw: r"x = y" if raw else None
    )

    report = pipeline.convert_pdf(
        str(pdf), str(tmp_path / "out"), isolate=False, do_ocr=False,
        formula_engine="rapidocr",
    )

    text_items = [item for item in report["elements"][0]["items"] if item["type"] == "text"]
    assert any("Equations follow:" in item["text"] for item in text_items)
    assert not any("x = y" in item["text"] for item in text_items)
    assert report["stats"]["formula_text_duplicates_removed"] == 1
    assert report["stats"]["formula_text_duplicates_remaining"] == 0


def test_formula_exclusion_does_not_change_non_overlapping_text(monkeypatch, tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=500, height=700)
    page.insert_text((80, 100), "Ordinary body text", fontsize=12)
    page.insert_text((80, 160), "x = y", fontsize=12)
    pdf = tmp_path / "separate-formula-text.pdf"
    doc.save(pdf)
    doc.close()
    monkeypatch.setattr(
        pipeline.layout_mod,
        "detect_layout",
        lambda *args, **kwargs: [[
            {
                "page": 1,
                "bbox_pdf": [60, 75, 300, 110],
                "visual_class": "text",
                "confidence": 0.8,
            },
            {
                "page": 1,
                "bbox_pdf": [60, 135, 250, 170],
                "visual_class": "formula",
                "confidence": 0.9,
            },
        ]],
    )
    monkeypatch.setattr(
        pipeline.formulas, "native_formula_latex", lambda raw: r"x = y" if raw else None
    )

    report = pipeline.convert_pdf(
        str(pdf), str(tmp_path / "out"), isolate=False, do_ocr=False,
        formula_engine="rapidocr",
    )

    text_items = [item for item in report["elements"][0]["items"] if item["type"] == "text"]
    assert any(item["text"] == "Ordinary body text" for item in text_items)
    assert report["stats"]["formula_text_duplicates_removed"] == 0
    assert report["stats"]["formula_text_duplicates_remaining"] == 0


def test_partial_stacked_formula_output_preserves_unrepresented_native_row(
    monkeypatch, tmp_path,
):
    doc = fitz.open()
    page = doc.new_page(width=500, height=700)
    page.insert_text((100, 130), "x_i = 1", fontsize=12)
    page.insert_text((100, 165), "y_i = 2", fontsize=12)
    pdf = tmp_path / "partial-stacked-formula.pdf"
    doc.save(pdf)
    doc.close()
    region = [80, 105, 300, 180]
    monkeypatch.setattr(
        pipeline.layout_mod,
        "detect_layout",
        lambda *args, **kwargs: [[
            {
                "page": 1,
                "bbox_pdf": region,
                "visual_class": "text",
                "confidence": 0.8,
            },
            {
                "page": 1,
                "bbox_pdf": region,
                "visual_class": "formula",
                "confidence": 0.9,
            },
        ]],
    )
    monkeypatch.setattr(
        pipeline.formulas,
        "native_formula_latex",
        lambda raw: r"x_i = 1" if "x_i" in raw else None,
    )
    monkeypatch.setattr(
        pipeline.formulas,
        "ocr_formula_latex",
        lambda *args, **kwargs: (None, 0.0, "test"),
    )
    monkeypatch.setattr(pipeline.text_mod, "save_image", lambda *args, **kwargs: None)

    report = pipeline.convert_pdf(
        str(pdf), str(tmp_path / "out"), isolate=False, do_ocr=False,
        formula_engine="rapidocr",
    )

    items = report["elements"][0]["items"]
    assert any(item["type"] == "formula" and item["text"] == "x_i = 1" for item in items)
    assert any(item["type"] == "text" and "y_i = 2" in item["text"] for item in items)
    assert not any(item["type"] == "text" and "x_i = 1" in item["text"] for item in items)


def test_long_stacked_formula_region_is_split_before_length_gate(monkeypatch, tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=500, height=700)
    rows = [
        "x_i = 1 and a very long native equation fragment " * 3,
        "y_i = 2 and a very long native equation fragment " * 3,
        "z_i = 3 and a very long native equation fragment " * 3,
    ]
    for y, row in zip((130, 165, 200), rows):
        page.insert_text((100, y), row, fontsize=8)
    pdf = tmp_path / "long-stacked-formulas.pdf"
    doc.save(pdf)
    doc.close()
    monkeypatch.setattr(
        pipeline.layout_mod,
        "detect_layout",
        lambda *args, **kwargs: [[{
            "page": 1,
            "bbox_pdf": [80, 105, 490, 215],
            "visual_class": "formula",
            "confidence": 0.9,
        }]],
    )

    def recognize_line(page, rect, **kwargs):
        return "x_i = 1", 0.8, "test"

    monkeypatch.setattr(pipeline.formulas, "ocr_formula_latex", recognize_line)
    report = pipeline.convert_pdf(
        str(pdf), str(tmp_path / "out"), isolate=False, do_ocr=False,
        formula_engine="rapidocr",
    )

    formula_items = [
        item for page_result in report["elements"]
        for item in page_result["items"] if item["type"] == "formula"
    ]
    assert len(formula_items) == 3


def test_born_digital_formula_uses_native_text_before_pix2tex(monkeypatch, tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=500, height=700)
    page.insert_text((100, 130), "x = y", fontsize=12)
    pdf = tmp_path / "native-formula.pdf"
    doc.save(pdf)
    doc.close()
    monkeypatch.setattr(
        pipeline.layout_mod,
        "detect_layout",
        lambda *args, **kwargs: [[{
            "page": 1,
            "bbox_pdf": [80, 105, 300, 145],
            "visual_class": "formula",
            "confidence": 0.9,
        }]],
    )
    monkeypatch.setattr(
        pipeline.formulas,
        "native_formula_latex",
        lambda raw: r"x = y" if raw else None,
    )

    def pix2tex_must_not_run(*args, **kwargs):
        raise AssertionError("image recognizer should not run for reliable native math")

    monkeypatch.setattr(pipeline.formulas, "ocr_formula_latex", pix2tex_must_not_run)
    report = pipeline.convert_pdf(
        str(pdf), str(tmp_path / "out"), isolate=False, do_ocr=False,
        formula_engine="pix2tex",
    )

    item = report["elements"][0]["items"][0]
    assert item["type"] == "formula"
    assert item["engine"] == "native"


def test_formula_recognition_retries_lower_dpi_before_image_fallback(monkeypatch, tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=500, height=700)
    page.insert_text((100, 130), "x = y", fontsize=12)
    pdf = tmp_path / "multiscale-formula.pdf"
    doc.save(pdf)
    doc.close()
    monkeypatch.setattr(
        pipeline.layout_mod,
        "detect_layout",
        lambda *args, **kwargs: [[{
            "page": 1,
            "bbox_pdf": [80, 105, 300, 145],
            "visual_class": "formula",
            "confidence": 0.9,
        }]],
    )
    monkeypatch.setattr(pipeline.formulas, "native_formula_latex", lambda raw: None)
    attempted_dpis = []

    def recognize_at_scale(page, rect, *, dpi, **kwargs):
        attempted_dpis.append(dpi)
        if dpi == 300:
            return r"\mu_{2 ,", 0.99, "pix2tex"
        return "x + y = a", 0.9, "pix2tex"

    monkeypatch.setattr(pipeline.formulas, "ocr_formula_latex", recognize_at_scale)
    report = pipeline.convert_pdf(
        str(pdf), str(tmp_path / "out"), isolate=False, do_ocr=False,
        formula_engine="pix2tex", formula_dpi=300,
    )

    formula_items = [
        item for page_result in report["elements"]
        for item in page_result["items"] if item["type"] == "formula"
    ]
    assert attempted_dpis == [300, 200]
    assert len(formula_items) == 1
    assert report["stats"]["formula_fallback_images"] == 0
