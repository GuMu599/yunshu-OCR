"""The detector's own class names are the source of layout semantics."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md import layout  # noqa: E402


def test_doclayout_class_names_map_to_pipeline_semantics():
    names = {
        0: "title",
        1: "plain text",
        2: "abandon",
        3: "figure",
        4: "figure_caption",
        5: "table",
        6: "table_caption",
        7: "table_footnote",
        8: "isolate_formula",
        9: "formula_caption",
    }

    assert [layout.semantic_class(names, class_id) for class_id in names] == [
        "title", "text", "artifact", "figure", "text",
        "table", "text", "text", "formula", "text",
    ]


def test_class_ids_are_not_assumed_when_model_metadata_changes_order():
    names = {0: "isolate_formula", 8: "title"}
    assert layout.semantic_class(names, 0) == "formula"
    assert layout.semantic_class(names, 8) == "title"


def test_unknown_model_class_is_not_silently_treated_as_text():
    assert layout.semantic_class({42: "new_unreviewed_class"}, 42) == "unknown"
