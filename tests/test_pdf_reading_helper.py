import importlib.util
import json
import os
from pathlib import Path

import fitz


HELPER = Path(__file__).resolve().parents[1] / "tools" / "pdf-reading" / "pdf2md.py"


def _load_helper():
    spec = importlib.util.spec_from_file_location("yunshu_pdf_reading", HELPER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _make_pdf(path: Path, pages: int = 1) -> None:
    doc = fitz.open()
    for index in range(pages):
        page = doc.new_page(width=300, height=400)
        page.insert_text((40, 60), f"page {index + 1}")
    doc.save(path)
    doc.close()


def test_ensure_invalidates_same_mtime_pdf_when_content_changes(monkeypatch, tmp_path):
    helper = _load_helper()
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"first-pdf-content")
    fixed_ns = 1_700_000_000_000_000_000
    os.utime(pdf, ns=(fixed_ns, fixed_ns))
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        out = Path(command[command.index("--output") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "source.md").write_text("converted", encoding="utf-8")
        (out / "layout.json").write_text('{"elements": []}', encoding="utf-8")
        (out / "report.json").write_text('{"stats": {}, "pages": 1}', encoding="utf-8")

    monkeypatch.setattr(helper.subprocess, "run", fake_run)

    first = helper.cmd_ensure(str(pdf))
    second = helper.cmd_ensure(str(pdf))
    pdf.write_bytes(b"other-pdf-content")
    os.utime(pdf, ns=(fixed_ns, fixed_ns))
    third = helper.cmd_ensure(str(pdf))

    assert first["cached"] is False
    assert second["cached"] is True
    assert third["cached"] is False
    assert len(calls) == 2
    binding = json.loads((tmp_path / "source_pdf2md" / "binding.json").read_text(encoding="utf-8"))
    assert binding["source"]["sha256"]
    assert binding["artifacts"]["markdown"].endswith("source.md")


def test_locate_returns_file_page_bbox_and_page_label(tmp_path):
    helper = _load_helper()
    pdf = tmp_path / "paper.pdf"
    _make_pdf(pdf, pages=2)
    out = tmp_path / "paper_pdf2md"
    out.mkdir()
    (out / "layout.json").write_text(
        json.dumps({
            "elements": [
                {"page": 2, "items": [{
                    "type": "table",
                    "content_type": "BODY",
                    "bbox_pdf": [20, 30, 280, 200],
                    "text": "核心结论 42",
                    "markdown": "| 核心结论 | 42 |",
                    "confidence": 0.91,
                    "structure_quality": 0.88,
                }]},
            ],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    result = helper.cmd_locate(str(pdf), "核心结论")

    assert result["ok"] is True
    assert result["hits"][0]["page"] == 2
    assert result["hits"][0]["page_label"] == "2"
    assert result["hits"][0]["bbox_pdf"] == [20, 30, 280, 200]
    assert result["hits"][0]["type"] == "table"


def test_render_page_is_an_explicit_full_page_fallback(tmp_path):
    helper = _load_helper()
    pdf = tmp_path / "paper.pdf"
    _make_pdf(pdf)

    result = helper.cmd_render_page(str(pdf), 1, dpi=144)

    assert result["ok"] is True
    assert result["mode"] == "full_page"
    assert result["page"] == 1
    assert result["page_label"] == "1"
    assert result["bbox"] == [0.0, 0.0, 300.0, 400.0]
    assert Path(result["image"]).exists()


def test_binding_becomes_stale_when_generated_markdown_is_tampered(monkeypatch, tmp_path):
    helper = _load_helper()
    pdf = tmp_path / "source.pdf"
    pdf.write_bytes(b"pdf-content")

    def fake_run(command, **kwargs):
        out = Path(command[command.index("--output") + 1])
        out.mkdir(parents=True, exist_ok=True)
        (out / "source.md").write_text("trusted conversion", encoding="utf-8")
        (out / "layout.json").write_text('{"elements": []}', encoding="utf-8")
        (out / "report.json").write_text('{"stats": {}, "pages": 1}', encoding="utf-8")

    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    helper.cmd_ensure(str(pdf))
    (tmp_path / "source_pdf2md" / "source.md").write_text("tampered", encoding="utf-8")

    result = helper.cmd_info(str(pdf))

    assert result["binding_valid"] is False
    assert result["ok"] is False


def test_converter_fingerprint_covers_all_engine_code_and_model_lock():
    helper = _load_helper()
    relative = {path.relative_to(helper._REPO).as_posix() for path in helper._converter_files()}

    assert "pdf2md/formulas.py" in relative
    assert "pdf2md/tables.py" in relative
    assert "pdf2md/normalize.py" in relative
    assert "models/models.lock.json" in relative


def test_locate_normalizes_spacing_in_table_labels(tmp_path):
    helper = _load_helper()
    pdf = tmp_path / "paper.pdf"
    _make_pdf(pdf)
    out = tmp_path / "paper_pdf2md"
    out.mkdir()
    (out / "layout.json").write_text(
        json.dumps({
            "elements": [{"page": 1, "items": [{
                "type": "text",
                "bbox_pdf": [20, 30, 280, 60],
                "text": "表2 主要结果",
                "markdown": "表2 主要结果",
            }]}],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    result = helper.cmd_locate(str(pdf), "表 2")

    assert result["count"] == 1
