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


def test_empty_native_ok():
    rep = textloss.coverage_report([""], [""])
    assert rep[0]["flag"] == "ok"
    assert rep[0]["ratio"] == 1.0
