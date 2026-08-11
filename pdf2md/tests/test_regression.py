"""Manifest-driven document regression checks use observable output contracts."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md.regression import evaluate_report  # noqa: E402


def _report():
    return {
        "meta": {"title": "Graphene Study"},
        "stats": {
            "images": 2, "tables": 0, "table_images": 0,
            "formulas": 0, "inline_formulas": 0,
            "formula_fallback_images": 0,
        },
        "quality": {"duplicate_text_count": 0, "status": "ok"},
        "elements": [{"page": 1, "items": [
            {"reading_order": 1, "type": "image", "text": ""},
            {"reading_order": 2, "type": "text", "text": "Fig. 1 result"},
            {"reading_order": 3, "type": "text", "text": "Conclusion"},
        ]}],
    }


def test_report_satisfies_structural_expectations():
    expected = {
        "title": "Graphene Study", "images": 2, "duplicate_text_max": 0,
        "forbidden_types": ["table_image"],
        "order": [["Fig. 1", "Conclusion"]],
    }
    result = evaluate_report(_report(), expected)
    assert result["passed"] is True
    assert result["failures"] == []


def test_order_matching_ignores_spacing_and_caption_punctuation_noise():
    report = _report()
    report["elements"][0]["items"][1]["text"] = "Fig£®1 result"
    report["elements"][0]["items"][2]["text"] = "Con clusion"
    result = evaluate_report(report, {"order": [["Fig. 1", "Conclusion"]]})
    assert result["passed"] is True


def test_report_checks_authors():
    report = _report()
    report["meta"]["authors"] = "Correct Author"
    result = evaluate_report(report, {"authors": "Wrong Author"})
    assert result["passed"] is False
    assert result["failures"][0].startswith("authors:")


def test_report_explains_failed_expectations():
    result = evaluate_report(_report(), {"images": 3, "order": [["Conclusion", "Fig. 1"]]})
    assert result["passed"] is False
    assert any("images" in failure for failure in result["failures"])
    assert any("order" in failure for failure in result["failures"])


def test_formula_expectation_can_require_a_nonzero_minimum():
    report = _report()
    failed = evaluate_report(report, {"formulas_min": 1})
    assert failed["passed"] is False
    assert failed["failures"] == ["formulas_min: expected >= 1, got 0"]

    report["stats"]["formulas"] = 2
    assert evaluate_report(report, {"formulas_min": 1})["passed"] is True


def test_inline_formula_expectation_has_an_independent_minimum():
    report = _report()
    failed = evaluate_report(report, {"inline_formulas_min": 2})
    assert failed["passed"] is False
    assert failed["failures"] == ["inline_formulas_min: expected >= 2, got 0"]

    report["stats"]["inline_formulas"] = 3
    assert evaluate_report(report, {"inline_formulas_min": 2})["passed"] is True


def test_formula_fallback_image_expectation_has_a_maximum():
    report = _report()
    report["stats"]["formula_fallback_images"] = 2

    failed = evaluate_report(report, {"formula_fallback_images_max": 0})

    assert failed["passed"] is False
    assert failed["failures"] == ["formula_fallback_images_max: expected <= 0, got 2"]


def test_formula_text_duplicate_expectation_requires_the_metric_and_enforces_maximum():
    report = _report()

    missing = evaluate_report(report, {"formula_text_duplicates_remaining_max": 0})
    assert missing["passed"] is False
    assert missing["failures"] == ["formula_text_duplicates_remaining: missing"]

    report["stats"]["formula_text_duplicates_remaining"] = 1
    failed = evaluate_report(report, {"formula_text_duplicates_remaining_max": 0})
    assert failed["passed"] is False
    assert failed["failures"] == [
        "formula_text_duplicates_remaining: expected <= 0, got 1"
    ]

    report["stats"]["formula_text_duplicates_remaining"] = 0
    assert evaluate_report(
        report, {"formula_text_duplicates_remaining_max": 0}
    )["passed"] is True
