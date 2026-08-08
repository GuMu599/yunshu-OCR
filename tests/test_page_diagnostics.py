import sys
from pathlib import Path

import fitz


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


def test_page_diagnostic_routes_clean_native_page_without_ocr():
    from page_diagnostics import PageSignals, diagnose_page

    result = diagnose_page(PageSignals(
        page=1, width=600, height=800, native_characters=1800,
        valid_character_ratio=0.995, replacement_ratio=0.0,
        control_character_ratio=0.0, text_coverage=0.42,
        overlap_ratio=0.01, image_coverage=0.08,
        block_count=24, crossed_reading_edges=0,
    ))

    assert result.status == "native_pass"
    assert result.repair_regions == []


def test_page_diagnostic_routes_corrupt_regions_to_ocr():
    from page_diagnostics import PageSignals, diagnose_page

    result = diagnose_page(PageSignals(
        page=2, width=600, height=800, native_characters=120,
        valid_character_ratio=0.62, replacement_ratio=0.08,
        control_character_ratio=0.03, text_coverage=0.07,
        overlap_ratio=0.21, image_coverage=0.80,
        block_count=6, crossed_reading_edges=4,
        suspicious_regions=[[40, 100, 560, 740]],
    ))

    assert result.status == "ocr_required"
    assert result.repair_regions == [[40, 100, 560, 740]]
    assert "low_native_retention" in result.reasons
    assert "reading_order_crossing" in result.reasons


def test_layout_anomalies_with_clean_native_text_do_not_force_ocr():
    from page_diagnostics import PageSignals, diagnose_page

    result = diagnose_page(PageSignals(
        page=3, width=600, height=800, native_characters=1900,
        valid_character_ratio=0.998, replacement_ratio=0.0,
        control_character_ratio=0.0, text_coverage=0.4,
        overlap_ratio=0.12, image_coverage=0.1,
        block_count=28, crossed_reading_edges=5,
    ))

    assert result.status == "native_pass"
    assert "overlapping_text_blocks" in result.reasons
    assert "reading_order_crossing" in result.reasons


def test_extract_page_signals_keeps_font_geometry_and_column_hints(tmp_path):
    from page_diagnostics import extract_page_signals

    path = tmp_path / "columns.pdf"
    document = fitz.open()
    page = document.new_page(width=600, height=800)
    page.insert_textbox(fitz.Rect(30, 80, 270, 360), "Left column text " * 60, fontsize=10)
    page.insert_textbox(fitz.Rect(330, 80, 570, 360), "Right column text " * 60, fontsize=10)
    document.save(path)
    document.close()

    signals = extract_page_signals(path)

    assert len(signals) == 1
    assert signals[0].native_characters > 400
    assert signals[0].block_count >= 2
    assert signals[0].column_count == 2
    assert signals[0].native_elements
    assert {"font_name", "font_size", "bbox_pdf", "column_hint"} <= signals[0].native_elements[0].keys()


def test_native_element_boxes_are_clipped_to_page_bounds():
    from page_diagnostics import _native_elements

    raw = {"blocks": [{
        "type": 0, "bbox": (-2, -1, 605, 810),
        "lines": [{"spans": [{"text": "Clipped", "font": "Test", "size": 10, "color": 0}]}],
    }]}
    elements = _native_elements(raw, fitz.Rect(0, 0, 600, 800))

    assert elements[0]["bbox_pdf"] == [0.0, 0.0, 600.0, 800.0]
    assert elements[0]["bbox_normalized"] == [0.0, 0.0, 1.0, 1.0]
