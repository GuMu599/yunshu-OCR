"""表格结构度量: TEDS (Tree Edit Distance based Similarity) 与逐格 CER.

TEDS 定义沿用 Zhong et al. (PubTabNet): 把表格 HTML 解析成有序树,
用 Zhang-Shasha 树编辑距离归一化: TEDS = 1 - TED / (|T1| + |T2|).
单元格文本并入 td/th 节点的 relabel 成本 (1 - 字符相似度).
零第三方依赖.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from .table_html import parse_html_table

_TABLE_TAGS = {"table", "tr", "td", "th", "thead", "tbody", "tfoot"}
_CELL_TAGS = {"td", "th"}


@dataclass
class Node:
    tag: str
    text: str = ""
    children: list["Node"] = field(default_factory=list)


def _walk(node: Node):
    yield node
    for c in node.children:
        yield from _walk(c)


class _TreeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root: Node | None = None
        self._stack: list[Node] = []

    def handle_starttag(self, tag, attrs) -> None:  # noqa: ANN001
        t = tag.lower()
        if t in _TABLE_TAGS:
            node = Node(t)
            if self._stack:
                self._stack[-1].children.append(node)
            elif self.root is None:
                self.root = node
            self._stack.append(node)

    def handle_endtag(self, tag) -> None:  # noqa: ANN001
        if tag.lower() in _TABLE_TAGS and self._stack:
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        if self._stack and self._stack[-1].tag in _CELL_TAGS:
            self._stack[-1].text += data


def html_to_tree(html: str) -> Node | None:
    """表格 HTML → 有序树. 无表格 / 解析失败返回 None."""
    if not html or "<table" not in html.lower():
        return None
    parser = _TreeParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return None
    if parser.root is None:
        return None
    for node in _walk(parser.root):
        if node.tag in _CELL_TAGS:
            node.text = re.sub(r"[ \t]+", " ", node.text.strip())
    return parser.root


def _count(node: Node) -> int:
    return 1 + sum(_count(c) for c in node.children)


# ---------- 树编辑距离 ----------


def _char_sim(x: str, y: str) -> float:
    if x == y:
        return 1.0
    if not x or not y:
        return 0.0
    d = levenshtein(x, y)
    return 1.0 - d / max(len(x), len(y))


def _relabel(a: Node, b: Node) -> float:
    if a.tag == b.tag and a.tag not in _CELL_TAGS:
        return 0.0  # 结构标签相同 (table/tr/thead/...) 无成本
    if a.tag in _CELL_TAGS and b.tag in _CELL_TAGS:
        return 1.0 - _char_sim(a.text, b.text)
    return 1.0


def tree_edit_distance(t1: Node, t2: Node) -> float:
    """有序树编辑距离 (定义式 + 记忆化, 无需第三方依赖).

    递归定义: forest(∅,fr)=|fr|, forest(fl,∅)=|fl|, 否则取
    删除首节点 / 插入首节点 / relabel 首节点三者最小。
    可达森林只可能是某节点子树的某个后缀 → 状态数 O(|T1|·|T2|)。
    该实现即标准树编辑距离定义, 比 keyroot 分块的 Zhang-Shasha 更不易出错。
    """
    memo: dict[tuple, float] = {}

    def forest(fl: tuple[Node, ...], fr: tuple[Node, ...]) -> float:
        key = (tuple(id(x) for x in fl), tuple(id(x) for x in fr))
        cached = memo.get(key)
        if cached is not None:
            return cached
        if not fl:
            res = float(len(fr))
        elif not fr:
            res = float(len(fl))
        else:
            delete = 1.0 + forest(fl[1:], fr)
            insert = 1.0 + forest(fl, fr[1:])
            match = (
                _relabel(fl[0], fr[0])
                + forest(tuple(fl[0].children), tuple(fr[0].children))
                + forest(fl[1:], fr[1:])
            )
            res = min(delete, insert, match)
        memo[key] = res
        return res

    return forest((t1,), (t2,))


# ---------- 度量 ----------


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) > 2000 or len(b) > 2000:
        return max(len(a), len(b))  # 防病态长文本拖垮 O(n*m)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def teds(gold_html: str, pred_html: str) -> float:
    """结构相似度 [0,1]; 任一侧无法解析返回 0."""
    t1 = html_to_tree(gold_html)
    t2 = html_to_tree(pred_html)
    if t1 is None or t2 is None:
        return 0.0
    ted = tree_edit_distance(t1, t2)
    total = _count(t1) + _count(t2)
    return max(0.0, 1.0 - ted / max(1, total))


def cell_cer(gold_html: str, pred_html: str) -> float:
    """逐格字符错误率: sum(lev) / max(1, sum(黄金格字符数)). 网格不兼容返回 1."""
    g = parse_html_table(gold_html)
    p = parse_html_table(pred_html)
    if g is None or p is None:
        return 1.0
    rows = max(g.rows, p.rows)
    cols = max(g.cols, p.cols)
    gold_chars = 0
    errors = 0
    for r in range(rows):
        for c in range(cols):
            gt = g.text_at(r, c) if r < g.rows and c < g.cols else ""
            pt = p.text_at(r, c) if r < p.rows and c < p.cols else ""
            errors += levenshtein(gt, pt)
            gold_chars += len(gt)
    return errors / max(1, gold_chars)
