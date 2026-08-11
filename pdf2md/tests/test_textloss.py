"""文字不丢失门禁测试"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md import textloss  # noqa: E402


def test_full_coverage_ok():
    rep = textloss.coverage_report(["hello world 123"], ["hello world 123 extra"])
    assert rep[0]["flag"] == "ok"
    assert rep[0]["ratio"] >= 1.0


def test_lost_text_suspect():
    # 原生 100 字符, MD 只恢复 40 → suspect
    native = "the quick brown fox jumps over the lazy dog a b c d e f g h i j k"
    md = "the quick brown fox"
    rep = textloss.coverage_report([native], [md])
    assert rep[0]["flag"] == "suspect"
    assert rep[0]["ratio"] < 0.9


def test_empty_native_cannot_be_reported_as_verified_ok():
    rep = textloss.coverage_report([""], [""])
    assert rep[0]["flag"] == "unverifiable"
    assert "no_native_reference" in rep[0]["warnings"]
    assert "empty_output" in rep[0]["warnings"]


def test_equal_length_unrelated_output_is_suspect():
    rep = textloss.coverage_report(["abcdef"], ["uvwxyz"])
    assert rep[0]["ratio"] == 1.0
    assert rep[0]["content_recall"] == 0.0
    assert rep[0]["flag"] == "suspect"


def test_reordered_output_is_suspect_even_when_all_tokens_exist():
    rep = textloss.coverage_report(
        ["one two three four five six"],
        ["four five six one two three"],
    )
    assert rep[0]["content_recall"] == 1.0
    assert rep[0]["order_recall"] < 0.85
    assert rep[0]["flag"] == "suspect"


def test_markdown_formatting_does_not_hide_matching_content():
    native = "Section one explains the measured result 123."
    markdown = "## Section one\n\nexplains the **measured** result 123."
    rep = textloss.coverage_report([native], [markdown])
    assert rep[0]["content_recall"] == 1.0
    assert rep[0]["order_recall"] == 1.0
    assert rep[0]["flag"] == "ok"


def test_duplicate_markdown_is_reported_even_when_character_coverage_is_high():
    native = "First unique sentence.\nSecond unique sentence."
    md = "First unique sentence.\nSecond unique sentence.\nFirst unique sentence."
    rep = textloss.coverage_report([native], [md])
    assert rep[0]["flag"] == "suspect"
    assert rep[0]["duplicate_lines"] == 1
    assert "duplicate_text" in rep[0]["warnings"]
