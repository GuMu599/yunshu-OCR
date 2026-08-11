"""Visual detector labels are hints; content evidence decides semantics."""

import io
import sys
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md.visual import analyze_visual_region  # noqa: E402


def _image_bytes() -> bytes:
    image = Image.new("RGB", (400, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.line((10, 160, 380, 20), fill="black", width=4)
    draw.line((10, 160, 380, 160), fill="black", width=2)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def _table_image_bytes() -> bytes:
    image = Image.new("RGB", (400, 180), "white")
    draw = ImageDraw.Draw(image)
    for x in (10, 130, 260, 390):
        draw.line((x, 10, x, 170), fill="black", width=2)
    for y in (10, 50, 90, 130, 170):
        draw.line((10, y, 390, y), fill="black", width=2)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def test_raster_figure_mislabeled_as_table_becomes_image():
    doc = fitz.open()
    page = doc.new_page(width=500, height=700)
    region = fitz.Rect(50, 100, 450, 280)
    page.insert_image(region, stream=_image_bytes())
    page.insert_text((55, 302), "Fig. 1 Raman spectra of samples", fontsize=10)

    result = analyze_visual_region(page, list(region), "table")

    assert result["semantic_class"] == "image"
    assert result["reason"] in {"raster_visual", "figure_caption"}
    assert result["evidence"]["caption_kind"] == "figure"
    doc.close()


def test_raster_table_with_table_caption_stays_table_candidate():
    doc = fitz.open()
    page = doc.new_page(width=500, height=700)
    region = fitz.Rect(50, 100, 450, 280)
    page.insert_image(region, stream=_image_bytes())
    page.insert_text((55, 302), "Table 1 Experimental parameters", fontsize=10)

    result = analyze_visual_region(page, list(region), "table")

    assert result["semantic_class"] == "table"
    assert result["reason"] == "table_caption"
    doc.close()


def test_raster_table_without_caption_is_sent_to_table_recognition():
    doc = fitz.open()
    page = doc.new_page(width=500, height=700)
    region = fitz.Rect(50, 100, 450, 280)
    page.insert_image(region, stream=_table_image_bytes())

    result = analyze_visual_region(page, list(region), "table")

    assert result["semantic_class"] == "table"
    assert result["reason"] == "raster_table_candidate"
    doc.close()


def test_text_dominant_region_mislabeled_as_figure_becomes_text():
    doc = fitz.open()
    page = doc.new_page(width=500, height=700)
    region = fitz.Rect(40, 100, 460, 190)
    page.insert_textbox(
        region,
        "This is a normal paragraph with enough prose to be classified as text. "
        "It must not be exported as a scientific image.",
        fontsize=10,
    )

    result = analyze_visual_region(page, list(region), "figure")

    assert result["semantic_class"] == "text"
    assert result["reason"] == "text_dominant"
    doc.close()


def test_small_margin_visual_candidate_is_artifact():
    doc = fitz.open()
    page = doc.new_page(width=500, height=700)
    region = fitz.Rect(440, 10, 485, 30)

    result = analyze_visual_region(page, list(region), "figure")

    assert result["semantic_class"] == "artifact"
    assert result["reason"] == "small_margin_region"
    doc.close()


def test_tiny_top_header_fragment_is_artifact_even_if_caption_is_nearby():
    doc = fitz.open()
    page = doc.new_page(width=600, height=840)
    page.insert_text((100, 110), "Fig. 2 Scientific result", fontsize=10)
    region = fitz.Rect(80, 58, 100, 70)

    result = analyze_visual_region(page, list(region), "figure")

    assert result["semantic_class"] == "artifact"
    doc.close()


def test_text_heavy_parent_box_does_not_absorb_child_figure_caption():
    doc = fitz.open()
    page = doc.new_page(width=600, height=840)
    parent = fitz.Rect(60, 60, 540, 320)
    page.insert_textbox(fitz.Rect(70, 75, 300, 270), "Long prose paragraph " * 35, fontsize=8)
    page.insert_image(fitz.Rect(340, 110, 510, 230), stream=_image_bytes())
    page.insert_text((350, 250), "Fig. 6 result", fontsize=10)

    result = analyze_visual_region(page, list(parent), "table")

    assert result["semantic_class"] == "text"
    assert result["reason"] == "text_dominant"
    doc.close()


def test_tiny_text_only_figure_candidate_becomes_text():
    doc = fitz.open()
    page = doc.new_page(width=600, height=840)
    region = fitz.Rect(430, 680, 520, 700)
    page.insert_text((435, 695), "(Ed.: A, B)", fontsize=8)

    result = analyze_visual_region(page, list(region), "figure")

    assert result["semantic_class"] == "text"
    assert result["reason"] == "tiny_text_region"
    doc.close()


def test_native_text_table_evidence_precedes_text_dominance():
    doc = fitz.open()
    page = doc.new_page(width=600, height=840)
    region = fitz.Rect(60, 100, 540, 320)
    page.insert_text((80, 130), "Country  GDP  CPI  Exchange", fontsize=10)
    page.insert_text((80, 160), "China  6.6  1.4  4.6", fontsize=10)
    page.insert_text((80, 190), "Japan  1.2  5.4  3.7", fontsize=10)
    page.insert_text((80, 220), "Korea  4.3  7.3  1.5", fontsize=10)

    result = analyze_visual_region(page, list(region), "table")

    assert result["semantic_class"] == "table"
    assert result["reason"] == "table_evidence"
    doc.close()
