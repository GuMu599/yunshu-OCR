"""生成结果质量 lint — 反馈环: 对已知失败模式亮红.

用法:
    python -m pdf2md.lint <生成的.md>

检查项 (对应用户报告的症状):
  1. 标题含多个节号前缀  → 目录合并块被当成标题 (TOC-merge)
  2. 标题结尾带页码      → 目录条目被当成标题 (TOC-entry)
  3. 标题过长 (>60 字)   → 正文段落被当成标题
  4. 公式块含多个公式编号 → 多条堆叠公式被合并进一个块
  5. 公式块含乱码序列     → OCR 公式错译
退出码: 0 = 干净, 1 = 有问题
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def _section_prefixes(text: str) -> list[str]:
    return re.findall(r"\b\d+(?:\.\d+)+\s", text)


def lint_markdown(md: str) -> list[dict]:
    issues: list[dict] = []
    lines = md.splitlines()

    # ── 标题检查 ──
    for ln, line in enumerate(lines, 1):
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if not m:
            continue
        text = m.group(2).strip()
        prefixes = _section_prefixes(text)
        if len(prefixes) >= 2:
            issues.append({"kind": "heading_toc_merge", "line": ln, "detail": f"H{len(m.group(1))} 多条目录合并: {text[:60]}"})
            continue
        tm = re.match(r"^(\d+(?:\.\d+)*)\s+(.+?)\s+(\d+)\s*$", text)
        if tm and not re.search(r"\d", tm.group(2)):
            issues.append({"kind": "heading_toc_entry", "line": ln, "detail": f"H{len(m.group(1))} 目录带页码: {text[:60]}"})
            continue
        if len(text) > 60:
            issues.append({"kind": "heading_too_long", "line": ln, "detail": f"H{len(m.group(1))} 过长像正文: {text[:60]}…"})

    # ── 公式检查 ──
    for m in re.finditer(r"```latex\n(.*?)\n```", md, re.S):
        ln = md.count("\n", 0, m.start()) + 1
        body = m.group(1).strip()
        eqnums = re.findall(r"\(\d+\.\d+\)", body)
        if len(eqnums) >= 2:
            issues.append({"kind": "formula_merged", "line": ln, "detail": f"{len(eqnums)} 条公式合并: {body[:70]}"})
        garble = [g for g in ("↑", "↓", "²", "√{}", "±f", "ia2") if g in body]
        if len(garble) >= 2:
            issues.append({"kind": "formula_garble", "line": ln, "detail": f"疑似乱码 {garble}: {body[:70]}"})
        # 非字母数字符号占比过高 → 疑似结构崩坏
        visible = re.sub(r"\s", "", body)
        if visible:
            ratio = sum(1 for c in visible if not c.isalnum() and c not in "{}[]()+=-<>,.\\*'|") / len(visible)
            if ratio > 0.45:
                issues.append({"kind": "formula_garble", "line": ln, "detail": f"符号占比过高 {ratio:.2f}: {body[:70]}"})

    return issues


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: python -m pdf2md.lint <生成的.md>", file=sys.stderr)
        return 2
    md = Path(sys.argv[1]).read_text(encoding="utf-8")
    issues = lint_markdown(md)
    if not issues:
        print("LINT OK")
        return 0
    print(f"LINT: {len(issues)} 个问题")
    for it in issues:
        print(f"  L{it['line']:>5} [{it['kind']}] {it['detail']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
