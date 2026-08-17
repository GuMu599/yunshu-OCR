#!/usr/bin/env python3
"""Portable launcher for an installed Yunshu-OCR skill."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _find_repo() -> Path | None:
    script = Path(__file__).resolve()
    skill_root = script.parent.parent
    markers = (
        skill_root / "references" / "yunshu-ocr-root.txt",
        skill_root / ".yunshu-ocr-root",
    )
    for marker in markers:
        if marker.exists():
            candidate = Path(marker.read_text(encoding="utf-8").strip()).expanduser().resolve()
            if (candidate / "tools" / "pdf-reading" / "pdf2md.py").exists():
                return candidate
    for parent in script.parents:
        if (parent / "tools" / "pdf-reading" / "pdf2md.py").exists():
            return parent
    return None


def main() -> int:
    repo = _find_repo()
    if repo is None:
        print(json.dumps({
            "ok": False,
            "error": "yunshu-OCR repository not found",
            "hint": "reinstall this skill from the yunshu-OCR repository",
        }, ensure_ascii=False))
        return 2
    helper = repo / "tools" / "pdf-reading" / "pdf2md.py"
    completed = subprocess.run([sys.executable, str(helper), *sys.argv[1:]], cwd=str(repo))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
