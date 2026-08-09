"""TEDS 度量测试: 树编辑距离 (Zhang-Shasha vs 独立暴力对照) + teds/cell_cer"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md.teds import (  # noqa: E402
    Node,
    cell_cer,
    html_to_tree,
    levenshtein,
    teds,
    tree_edit_distance,
)


# ---------- 独立暴力对照 (测试内实现, 与生产实现无共享代码) ----------


def _node(tag: str, text: str = "", *children: Node) -> Node:
    n = Node(tag, text, list(children))
    return n


def _relabel_cost(a: Node, b: Node) -> float:
    if a.tag == b.tag and a.tag not in ("td", "th"):
        return 0.0
    if a.tag in ("td", "th") and b.tag in ("td", "th"):
        if a.text == b.text:
            return 0.0
        if not a.text or not b.text:
            return 1.0
        return 1.0 - (1.0 - levenshtein(a.text, b.text) / max(len(a.text), len(b.text)))
    return 1.0


def _brute_ted(n1: Node, n2: Node) -> float:
    memo: dict[tuple, float] = {}

    def forest(fl: tuple[Node, ...], fr: tuple[Node, ...]) -> float:
        key = (tuple(id(x) for x in fl), tuple(id(x) for x in fr))
        if key in memo:
            return memo[key]
        if not fl:
            return float(len(fr))
        if not fr:
            return float(len(fl))
        d = 1.0 + forest(fl[1:], fr)
        ins = 1.0 + forest(fl, fr[1:])
        m = _relabel_cost(fl[0], fr[0]) + forest(tuple(fl[0].children), tuple(fr[0].children)) + forest(fl[1:], fr[1:])
        res = min(d, ins, m)
        memo[key] = res
        return res

    return forest((n1,), (n2,))


def test_levenshtein():
    assert levenshtein("", "") == 0
    assert levenshtein("abc", "abc") == 0
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein("abc", "") == 3


def test_ted_matches_brute_identical():
    a = _node("table", "", _node("tr", "", _node("td", "x"), _node("td", "y")))
    assert tree_edit_distance(a, a) == 0.0
    assert _brute_ted(a, a) == 0.0


def test_ted_matches_brute_small_trees():
    cases = [
        # 单节点
        (_node("table"), _node("table")),
        (_node("table"), _node("tr")),
        # 结构差一列
        (
            _node("table", "", _node("tr", "", _node("td", "a"), _node("td", "b"))),
            _node("table", "", _node("tr", "", _node("td", "a"))),
        ),
        # 文本不同
        (
            _node("table", "", _node("tr", "", _node("td", "abc"))),
            _node("table", "", _node("tr", "", _node("td", "abd"))),
        ),
        # 子树 + rowspan 形状差异
        (
            _node("table", "", _node("tr", "", _node("td", "a"), _node("tr", "", _node("td", "b")))),
            _node("table", "", _node("tr", "", _node("td", "a"))),
        ),
    ]
    for a, b in cases:
        got = tree_edit_distance(a, b)
        want = _brute_ted(a, b)
        assert abs(got - want) < 1e-9, f"tree_edit_distance({a.tag},{b.tag}) = {got}, brute = {want}"


def test_teds_identical_is_one():
    html = "<table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>"
    assert teds(html, html) == 1.0


def test_teds_text_change_lowers():
    gold = "<table><tr><td>a</td><td>b</td></tr><tr><td>c</td><td>d</td></tr></table>"
    pred = "<table><tr><td>a</td><td>X</td></tr><tr><td>c</td><td>d</td></tr></table>"
    v = teds(gold, pred)
    assert 0.0 < v < 1.0


def test_teds_structure_change_lowers_more():
    gold = "<table><tr><td rowspan=\"2\">m</td><td>a</td></tr><tr><td>b</td></tr></table>"
    pred = "<table><tr><td>m</td><td>a</td></tr><tr><td>b</td><td>c</td></tr></table>"
    assert teds(gold, pred) < 1.0


def test_teds_unparsable_is_zero():
    assert teds("no table", "<table><tr><td>a</td></tr></table>") == 0.0
    assert teds("", "") == 0.0


def test_cell_cer_exact_zero():
    html = "<table><tr><td>abc</td><td>de</td></tr></table>"
    assert cell_cer(html, html) == 0.0


def test_cell_cer_incompatible_one():
    assert cell_cer("<table><tr><td>a</td></tr></table>", "no table") == 1.0


def test_cell_cer_wrong_within_tolerance():
    gold = "<table><tr><td>abc</td></tr></table>"
    pred = "<table><tr><td>abx</td></tr></table>"
    assert abs(cell_cer(gold, pred) - 1 / 3) < 1e-9
