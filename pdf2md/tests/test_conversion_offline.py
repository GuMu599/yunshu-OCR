"""PDF conversion does not open network connections after model installation."""

from __future__ import annotations

import socket
import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md import pipeline  # noqa: E402


def test_conversion_succeeds_with_socket_connections_denied(monkeypatch, tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.insert_text((50, 100), "Offline conversion text", fontsize=12)
    pdf = tmp_path / "offline.pdf"
    doc.save(pdf)
    doc.close()

    monkeypatch.setattr(
        pipeline.layout_mod,
        "detect_layout",
        lambda *args, **kwargs: [[{
            "page": 1,
            "bbox_pdf": [40, 80, 300, 120],
            "visual_class": "text",
            "confidence": 0.99,
        }]],
    )

    def deny_network(*args, **kwargs):
        raise AssertionError("conversion attempted a network connection")

    monkeypatch.setattr(socket, "create_connection", deny_network)
    monkeypatch.setattr(socket.socket, "connect", deny_network)

    report = pipeline.convert_pdf(
        str(pdf),
        str(tmp_path / "out"),
        isolate=False,
        do_ocr=False,
        use_table_model=False,
        formula_engine="rapidocr",
    )

    assert "Offline conversion text" in report["markdown"]
    assert report["offline"] is True
