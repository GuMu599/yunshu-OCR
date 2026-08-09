#!/usr/bin/env python3
"""yunshu-ocr 技能助手: 确保 PDF→MD 转换缓存 + 按需渲染 PDF 局部.

用法 (repo 根目录下运行, 或用任意 python 解释器):
  python .claude/skills/yunshu-ocr/pdf2md.py ensure <pdf> [--force]
  python .claude/skills/yunshu-ocr/pdf2md.py render <pdf> <page> <bbox> [--dpi 300] [--out out.png]
  python .claude/skills/yunshu-ocr/pdf2md.py info <pdf>

输出均为 JSON, 供 AI 解析。bbox 格式: "x0,y0,x1,y1" 或 "full"。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent.parent  # .claude/skills/<name>/ → repo 根
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _out_dir(pdf: str) -> Path:
    return Path(pdf).resolve().parent / (Path(pdf).stem + "_pdf2md")


def _md_path(pdf: str) -> Path:
    return _out_dir(pdf) / (Path(pdf).stem + ".md")


def cmd_ensure(pdf: str, force: bool = False) -> dict:
    pdf_path = Path(pdf)
    if not pdf_path.exists():
        print(json.dumps({"ok": False, "error": f"pdf not found: {pdf}"}))
        sys.exit(1)
    pdf_abs = str(pdf_path.resolve())
    out = _out_dir(pdf_abs)
    md = _md_path(pdf_abs)
    pdf_mtime = pdf_path.stat().st_mtime

    result: dict = {"ok": True, "pdf": pdf_abs, "md": str(md), "cached": False}
    if md.exists() and not force and pdf_mtime <= md.stat().st_mtime:
        result["cached"] = True
    else:
        try:
            subprocess.run(
                [sys.executable, "-m", "pdf2md.cli", pdf_abs, "--output", str(out)],
                cwd=str(_REPO), check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as exc:
            print(json.dumps({"ok": False, "error": f"conversion failed: {exc.stderr[-500:]}"}))
            sys.exit(2)
    layout = out / "layout.json"
    report = out / "report.json"
    result.update({
        "layout": str(layout) if layout.exists() else None,
        "report": str(report) if report.exists() else None,
    })
    if report.exists():
        try:
            r = json.loads(report.read_text(encoding="utf-8"))
            result["stats"] = r.get("stats", {})
            result["pages"] = r.get("pages")
        except Exception:
            pass
    print(json.dumps(result, ensure_ascii=False))
    return result


def cmd_render(pdf: str, page: int, bbox: str, dpi: int = 300, out: str | None = None) -> dict:
    import fitz  # noqa: PLC0415

    pdf_path = Path(pdf)
    if not pdf_path.exists():
        print(json.dumps({"ok": False, "error": f"pdf not found: {pdf}"}))
        sys.exit(1)
    doc = fitz.open(str(pdf_path))
    if not (1 <= page <= len(doc)):
        print(json.dumps({"ok": False, "error": f"page {page} out of range (1-{len(doc)})"}))
        sys.exit(1)
    page_obj = doc[page - 1]
    if bbox.lower() == "full":
        rect = page_obj.rect
    else:
        parts = [float(x) for x in bbox.split(",")]
        if len(parts) != 4:
            print(json.dumps({"ok": False, "error": "bbox must be x0,y0,x1,y1 or 'full'"}))
            sys.exit(1)
        rect = fitz.Rect(*parts) & page_obj.rect
    scale = max(1.0, dpi / 72.0)
    pix = page_obj.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
    out_path = Path(out) if out else (_out_dir(str(pdf_path.resolve())) / f"page{page:03d}_region.png")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(out_path))
    doc.close()
    print(json.dumps({
        "ok": True, "image": str(out_path), "page": page,
        "bbox": [rect.x0, rect.y0, rect.x1, rect.y1], "dpi": dpi,
    }, ensure_ascii=False))
    return {}


def cmd_info(pdf: str) -> dict:
    pdf_path = Path(pdf)
    out = _out_dir(str(pdf_path.resolve()))
    report = out / "report.json"
    md = _md_path(str(pdf_path.resolve()))
    if not md.exists():
        print(json.dumps({"ok": False, "converted": False, "hint": "run: ensure"}))
        return {}
    info: dict = {"ok": True, "converted": True, "md": str(md)}
    if report.exists():
        try:
            r = json.loads(report.read_text(encoding="utf-8"))
            info["stats"] = r.get("stats", {})
            info["pages"] = r.get("pages")
            info["coverage"] = r.get("coverage")
        except Exception:
            pass
    print(json.dumps(info, ensure_ascii=False))
    return info


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    pdf = sys.argv[2]
    if cmd == "ensure":
        cmd_ensure(pdf, force="--force" in sys.argv[3:])
    elif cmd == "info":
        cmd_info(pdf)
    elif cmd == "render":
        if len(sys.argv) < 5:
            print("render 需要 page 和 bbox 参数", file=sys.stderr)
            sys.exit(1)
        page = int(sys.argv[3])
        bbox = sys.argv[4]
        dpi = 300
        out = None
        rest = sys.argv[5:]
        for i, a in enumerate(rest):
            if a == "--dpi" and i + 1 < len(rest):
                dpi = int(rest[i + 1])
            if a == "--out" and i + 1 < len(rest):
                out = rest[i + 1]
        cmd_render(pdf, page, bbox, dpi=dpi, out=out)
    else:
        print(f"未知命令: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
