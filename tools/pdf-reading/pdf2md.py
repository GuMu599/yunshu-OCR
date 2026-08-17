#!/usr/bin/env python3
"""Yunshu-OCR PDF reading boundary.

Commands:
  python tools/pdf-reading/pdf2md.py ensure <pdf> [--force]
  python tools/pdf-reading/pdf2md.py info <pdf>
  python tools/pdf-reading/pdf2md.py locate <pdf> <query> [--page N] [--limit N]
  python tools/pdf-reading/pdf2md.py render <pdf> <page> <bbox> [--dpi 300] [--out out.png]
  python tools/pdf-reading/pdf2md.py render-page <pdf> <page> [--dpi 300] [--out out.png]

All commands print JSON. Page numbers are 1-based PDF file page numbers. ``bbox`` is
``x0,y0,x1,y1`` or ``full``.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_BINDING_SCHEMA = 1
def _out_dir(pdf: str) -> Path:
    path = Path(pdf).resolve()
    return path.parent / f"{path.stem}_pdf2md"


def _md_path(pdf: str) -> Path:
    path = Path(pdf).resolve()
    return _out_dir(str(path)) / f"{path.stem}.md"


def _binding_path(pdf: str) -> Path:
    return _out_dir(pdf) / "binding.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_fingerprint(pdf_path: Path) -> dict:
    stat = pdf_path.stat()
    return {
        "path": str(pdf_path.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": _sha256(pdf_path),
    }


def _converter_files() -> list[Path]:
    files = sorted((_REPO / "pdf2md").rglob("*.py"))
    files.extend([
        Path(__file__).resolve(),
        _REPO / "models" / "models.lock.json",
        _REPO / "requirements-lock.txt",
    ])
    return [path for path in files if path.exists()]


def _converter_fingerprint() -> str:
    digest = hashlib.sha256()
    for path in _converter_files():
        digest.update(str(path.relative_to(_REPO)).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _artifacts(pdf: str) -> dict[str, Path]:
    out = _out_dir(pdf)
    return {
        "markdown": _md_path(pdf),
        "layout": out / "layout.json",
        "report": out / "report.json",
        "binding": out / "binding.json",
    }


def _binding_is_valid(pdf: str, source: dict | None = None) -> bool:
    paths = _artifacts(pdf)
    if not all(paths[name].exists() for name in ("markdown", "layout", "report", "binding")):
        return False
    binding = _read_json(paths["binding"])
    if not binding or binding.get("schema") != _BINDING_SCHEMA:
        return False
    current_source = source or _source_fingerprint(Path(pdf).resolve())
    expected_artifact_hashes = binding.get("artifact_sha256")
    if not isinstance(expected_artifact_hashes, dict):
        return False
    current_artifact_hashes = {
        name: _sha256(paths[name]) for name in ("markdown", "layout", "report")
    }
    return (
        binding.get("source") == current_source
        and binding.get("converter_fingerprint") == _converter_fingerprint()
        and expected_artifact_hashes == current_artifact_hashes
    )


def _write_binding(pdf: str, source: dict) -> Path:
    paths = _artifacts(pdf)
    record = {
        "schema": _BINDING_SCHEMA,
        "source": source,
        "converter_fingerprint": _converter_fingerprint(),
        "artifacts": {
            "markdown": str(paths["markdown"]),
            "layout": str(paths["layout"]),
            "report": str(paths["report"]),
        },
        "artifact_sha256": {
            name: _sha256(paths[name]) for name in ("markdown", "layout", "report")
        },
    }
    paths["binding"].parent.mkdir(parents=True, exist_ok=True)
    temporary = paths["binding"].with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(paths["binding"])
    return paths["binding"]


def _page_label(pdf: str, page: int) -> str:
    import fitz  # noqa: PLC0415

    with fitz.open(str(Path(pdf).resolve())) as doc:
        if not 1 <= page <= len(doc):
            return str(page)
        page_obj = doc[page - 1]
        label = page_obj.get_label() if hasattr(page_obj, "get_label") else ""
        return label or str(page)


def _emit(result: dict) -> dict:
    print(json.dumps(result, ensure_ascii=False))
    return result


def _normalize_search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", "", normalized)


def cmd_ensure(pdf: str, force: bool = False) -> dict:
    pdf_path = Path(pdf).resolve()
    if not pdf_path.exists():
        _emit({"ok": False, "error": f"pdf not found: {pdf}"})
        raise SystemExit(1)

    pdf_abs = str(pdf_path)
    paths = _artifacts(pdf_abs)
    source = _source_fingerprint(pdf_path)
    cached = not force and _binding_is_valid(pdf_abs, source)

    if not cached:
        command = [
            sys.executable,
            "-m",
            "pdf2md.cli",
            pdf_abs,
            "--output",
            str(_out_dir(pdf_abs)),
            "--dpi",
            "300",
            "--formula-dpi",
            "300",
            "--image-dpi",
            "300",
            "--formula-engine",
            "auto",
            "--table-merge",
            "expand",
        ]
        try:
            subprocess.run(
                command,
                cwd=str(_REPO),
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = (exc.stderr or str(exc))[-800:]
            _emit({"ok": False, "pdf": pdf_abs, "error": f"conversion failed: {stderr}"})
            raise SystemExit(2)
        missing = [name for name in ("markdown", "layout", "report") if not paths[name].exists()]
        if missing:
            _emit({"ok": False, "pdf": pdf_abs, "error": f"conversion missing artifacts: {missing}"})
            raise SystemExit(2)
        _write_binding(pdf_abs, source)

    result: dict = {
        "ok": True,
        "pdf": pdf_abs,
        "md": str(paths["markdown"]),
        "layout": str(paths["layout"]),
        "report": str(paths["report"]),
        "binding": str(paths["binding"]),
        "binding_valid": True,
        "source_sha256": source["sha256"],
        "cached": cached,
    }
    report = _read_json(paths["report"])
    if report:
        result["stats"] = report.get("stats", {})
        result["pages"] = report.get("pages")
        result["coverage"] = report.get("coverage")
        result["quality"] = report.get("quality")
    return _emit(result)


def cmd_info(pdf: str) -> dict:
    pdf_path = Path(pdf).resolve()
    if not pdf_path.exists():
        return _emit({"ok": False, "converted": False, "error": f"pdf not found: {pdf}"})
    paths = _artifacts(str(pdf_path))
    converted = paths["markdown"].exists()
    if not converted:
        return _emit({"ok": False, "converted": False, "hint": "run: ensure"})
    source = _source_fingerprint(pdf_path)
    valid = _binding_is_valid(str(pdf_path), source)
    info: dict = {
        "ok": valid,
        "converted": True,
        "binding_valid": valid,
        "md": str(paths["markdown"]),
        "layout": str(paths["layout"]) if paths["layout"].exists() else None,
        "report": str(paths["report"]) if paths["report"].exists() else None,
        "binding": str(paths["binding"]) if paths["binding"].exists() else None,
        "source_sha256": source["sha256"],
    }
    if not valid:
        info["hint"] = "binding stale or incomplete; run: ensure"
    report = _read_json(paths["report"])
    if report:
        info["stats"] = report.get("stats", {})
        info["pages"] = report.get("pages")
        info["coverage"] = report.get("coverage")
        info["quality"] = report.get("quality")
        info["pdf_profile"] = report.get("pdf_profile")
    return _emit(info)


def cmd_locate(pdf: str, query: str, page: int | None = None, limit: int = 8) -> dict:
    pdf_path = Path(pdf).resolve()
    layout_path = _artifacts(str(pdf_path))["layout"]
    if not pdf_path.exists():
        return _emit({"ok": False, "error": f"pdf not found: {pdf}", "hits": []})
    layout = _read_json(layout_path)
    if not layout:
        return _emit({"ok": False, "error": "layout not found; run: ensure", "hits": []})
    needle = _normalize_search_text(query.strip())
    if not needle:
        return _emit({"ok": False, "error": "query must not be empty", "hits": []})

    hits = []
    label_cache: dict[int, str] = {}
    for page_record in layout.get("elements", []):
        file_page = int(page_record.get("page") or 0)
        if page is not None and file_page != page:
            continue
        for index, item in enumerate(page_record.get("items", [])):
            fields = [item.get("text"), item.get("markdown"), item.get("html")]
            body = "\n".join(value for value in fields if isinstance(value, str))
            folded = _normalize_search_text(body)
            if needle not in folded:
                continue
            label_cache.setdefault(file_page, _page_label(str(pdf_path), file_page))
            position = folded.find(needle)
            start = max(0, position - 80)
            end = min(len(body), position + len(query) + 160)
            hits.append({
                "page": file_page,
                "page_label": label_cache[file_page],
                "bbox_pdf": item.get("bbox_pdf"),
                "type": item.get("type"),
                "content_type": item.get("content_type"),
                "confidence": item.get("confidence"),
                "structure_quality": item.get("structure_quality"),
                "item_index": index,
                "preview": body[start:end].replace("\n", " ").strip(),
            })
    hits.sort(key=lambda hit: (hit["page"], hit["item_index"]))
    return _emit({
        "ok": True,
        "pdf": str(pdf_path),
        "query": query,
        "count": len(hits),
        "hits": hits[:max(1, limit)],
    })


def cmd_render(
    pdf: str,
    page: int,
    bbox: str,
    dpi: int = 300,
    out: str | None = None,
) -> dict:
    import fitz  # noqa: PLC0415

    pdf_path = Path(pdf).resolve()
    if not pdf_path.exists():
        _emit({"ok": False, "error": f"pdf not found: {pdf}"})
        raise SystemExit(1)
    doc = fitz.open(str(pdf_path))
    try:
        if not 1 <= page <= len(doc):
            _emit({"ok": False, "error": f"page {page} out of range (1-{len(doc)})"})
            raise SystemExit(1)
        page_obj = doc[page - 1]
        full_page = bbox.lower() == "full"
        if full_page:
            rect = page_obj.rect
        else:
            try:
                parts = [float(value) for value in bbox.split(",")]
            except ValueError:
                parts = []
            if len(parts) != 4:
                _emit({"ok": False, "error": "bbox must be x0,y0,x1,y1 or 'full'"})
                raise SystemExit(1)
            rect = fitz.Rect(*parts) & page_obj.rect
            if rect.is_empty:
                _emit({"ok": False, "error": "bbox does not intersect the PDF page"})
                raise SystemExit(1)
        scale = max(1.0, dpi / 72.0)
        pix = page_obj.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
        suffix = "full" if full_page else "region"
        out_path = Path(out) if out else _out_dir(str(pdf_path)) / f"page{page:03d}_{suffix}.png"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        pix.save(str(out_path))
        label = page_obj.get_label() if hasattr(page_obj, "get_label") else ""
        result = {
            "ok": True,
            "image": str(out_path.resolve()),
            "page": page,
            "page_label": label or str(page),
            "bbox": [rect.x0, rect.y0, rect.x1, rect.y1],
            "dpi": dpi,
            "mode": "full_page" if full_page else "bbox",
        }
    finally:
        doc.close()
    return _emit(result)


def cmd_render_page(pdf: str, page: int, dpi: int = 300, out: str | None = None) -> dict:
    return cmd_render(pdf, page, "full", dpi=dpi, out=out)


def _option(rest: list[str], name: str, default: str | None = None) -> str | None:
    if name not in rest:
        return default
    index = rest.index(name)
    return rest[index + 1] if index + 1 < len(rest) else default


def main() -> None:
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(1)
    command = sys.argv[1]
    pdf = sys.argv[2]
    rest = sys.argv[3:]
    if command == "ensure":
        cmd_ensure(pdf, force="--force" in rest)
    elif command == "info":
        cmd_info(pdf)
    elif command == "locate":
        if not rest:
            print("locate requires a query", file=sys.stderr)
            raise SystemExit(1)
        query = rest[0]
        page_value = _option(rest[1:], "--page")
        limit_value = _option(rest[1:], "--limit", "8")
        cmd_locate(
            pdf,
            query,
            page=int(page_value) if page_value else None,
            limit=int(limit_value or 8),
        )
    elif command == "render":
        if len(rest) < 2:
            print("render requires page and bbox", file=sys.stderr)
            raise SystemExit(1)
        cmd_render(
            pdf,
            int(rest[0]),
            rest[1],
            dpi=int(_option(rest[2:], "--dpi", "300") or 300),
            out=_option(rest[2:], "--out"),
        )
    elif command == "render-page":
        if not rest:
            print("render-page requires page", file=sys.stderr)
            raise SystemExit(1)
        cmd_render_page(
            pdf,
            int(rest[0]),
            dpi=int(_option(rest[1:], "--dpi", "300") or 300),
            out=_option(rest[1:], "--out"),
        )
    else:
        print(f"unknown command: {command}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
