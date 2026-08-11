"""Security-sensitive runtime dependency floors stay above known vulnerable releases."""

from pathlib import Path


def test_pillow_floor_in_both_requirement_sets_is_12_3_or_newer():
    repo = Path(__file__).resolve().parent.parent.parent
    for requirements in (repo / "requirements.txt", repo / "pdf2md" / "requirements.txt"):
        text = requirements.read_text(encoding="utf-8")
        assert "Pillow>=12.3.0" in text
