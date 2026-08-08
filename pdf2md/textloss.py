"""文字不丢失验证门禁.

逐页比对「PDF 原生文字(字母/数字/CJK)」vs「输出 MD 段内字母/数字/CJK」字符数。
ratio >= 0.9 视为 ok; 否则 suspect (报告, 不硬阻塞)。
注意: 公式/图片会额外增加 OCR 字符, 因此 md 计数通常 >= native 计数。
"""

from __future__ import annotations

import re


def _alnum_chars(s: str) -> int:
    return len(re.findall(r"[0-9A-Za-z一-鿿]", s))


def coverage_report(native_texts: list[str], page_md_texts: list[str]) -> list[dict]:
    """返回逐页报告. native_texts/page_md_texts 按页码 0-based 对齐."""
    report = []
    for i, (native, md) in enumerate(zip(native_texts, page_md_texts)):
        n = _alnum_chars(native or "")
        m = _alnum_chars(md or "")
        ratio = (m / n) if n else (1.0 if m else 1.0)
        report.append(
            {
                "page": i + 1,
                "native_chars": n,
                "md_chars": m,
                "ratio": round(ratio, 3),
                "flag": "ok" if ratio >= 0.9 else "suspect",
            }
        )
    return report
