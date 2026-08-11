"""文字不丢失验证门禁.

逐页比对「PDF 原生文字(字母/数字/CJK)」vs「输出 MD 段内字母/数字/CJK」字符数。
ratio >= 0.9 视为 ok; 否则 suspect (报告, 不硬阻塞)。
注意: 公式/图片会额外增加 OCR 字符, 因此 md 计数通常 >= native 计数。
"""

from __future__ import annotations

import re
from bisect import bisect_right
from collections import Counter
from itertools import zip_longest


def _alnum_chars(s: str) -> int:
    return len(re.findall(r"[0-9A-Za-z一-鿿]", s))


def _line_key(line: str) -> str:
    if line.lstrip().startswith(("![", "<!--", "```", "|")):
        return ""
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", line).lower()


def _duplicate_line_count(native: str, markdown: str) -> int:
    native_counts = Counter(k for line in native.splitlines() if len(k := _line_key(line)) >= 12)
    md_counts = Counter(k for line in markdown.splitlines() if len(k := _line_key(line)) >= 12)
    duplicate = 0
    for key, count in md_counts.items():
        if key in native_counts:
            duplicate += max(0, count - native_counts[key])
    return duplicate


def _content_tokens(text: str) -> list[str]:
    """Return formatting-independent lexical units for Latin and CJK text."""
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", str(text or ""))
    cleaned = re.sub(r"<!--.*?-->", " ", cleaned, flags=re.DOTALL)
    return [
        token.lower()
        for token in re.findall(r"[0-9A-Za-z]+|[\u4e00-\u9fff]", cleaned)
    ]


def _semantic_recall(native: str, markdown: str) -> tuple[float, float]:
    """Measure identity retention and monotonic reading order independently."""
    source = _content_tokens(native)
    output = _content_tokens(markdown)
    if not source:
        return 0.0, 0.0

    source_counts = Counter(source)
    output_counts = Counter(output)
    content_matches = sum(min(count, output_counts.get(token, 0)) for token, count in source_counts.items())
    content_recall = content_matches / len(source)

    positions: dict[str, list[int]] = {}
    for index, token in enumerate(output):
        positions.setdefault(token, []).append(index)
    last = -1
    ordered_matches = 0
    for token in source:
        candidates = positions.get(token, [])
        at = bisect_right(candidates, last)
        if at < len(candidates):
            last = candidates[at]
            ordered_matches += 1
    return content_recall, ordered_matches / len(source)


def coverage_report(native_texts: list[str], page_md_texts: list[str]) -> list[dict]:
    """返回逐页报告. native_texts/page_md_texts 按页码 0-based 对齐."""
    report = []
    for i, (native, md) in enumerate(zip_longest(native_texts, page_md_texts, fillvalue="")):
        n = _alnum_chars(native or "")
        m = _alnum_chars(md or "")
        ratio = (m / n) if n else 0.0
        content_recall, order_recall = _semantic_recall(native or "", md or "")
        duplicate_lines = _duplicate_line_count(native or "", md or "")
        warnings = []
        if not n:
            warnings.append("no_native_reference")
            if not m:
                warnings.append("empty_output")
            flag = "unverifiable"
        else:
            if ratio < 0.9:
                warnings.append("text_loss")
            if content_recall < 0.9:
                warnings.append("content_mismatch")
            if order_recall < 0.85:
                warnings.append("reading_order_mismatch")
            flag = "ok" if not warnings else "suspect"
        if duplicate_lines:
            warnings.append("duplicate_text")
            flag = "suspect"
        report.append(
            {
                "page": i + 1,
                "native_chars": n,
                "md_chars": m,
                "ratio": round(ratio, 3),
                "content_recall": round(content_recall, 3),
                "order_recall": round(order_recall, 3),
                "duplicate_lines": duplicate_lines,
                "warnings": warnings,
                "flag": flag,
            }
        )
    return report
