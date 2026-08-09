"""PDF 预检档案: 原生/扫描/混合判断"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import fitz

from pdf2md.pdf_profile import profile_pdf  # noqa: E402


def _native_pdf(n_pages=3):
    doc = fitz.open()
    for i in range(n_pages):
        page = doc.new_page(width=600, height=800)
        for j in range(20):
            page.insert_text(fitz.Point(50, 50 + j * 20),
                             f"Page {i} line {j} of normal prose text content that is long enough", fontsize=10)
    return doc


def _scanned_pdf(n_pages=3):
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.insert_text(fitz.Point(50, 50), "x", fontsize=1)
    pix = page.get_pixmap(dpi=60)
    png = pix.tobytes("png")
    out = fitz.open()
    for _ in range(n_pages):
        p = out.new_page(width=600, height=800)
        p.insert_image(fitz.Rect(0, 0, 600, 800), stream=png)
    return out


def test_native_pdf_profile(tmp_path):
    doc = _native_pdf()
    pdf = tmp_path / "native.pdf"
    doc.save(str(pdf))
    prof = profile_pdf(str(pdf))
    assert prof["mode"] == "native"
    assert prof["bottleneck"] == "layout"
    assert prof["ocr_needed"] is False


def test_scanned_pdf_profile(tmp_path):
    doc = _scanned_pdf()
    pdf = tmp_path / "scanned.pdf"
    doc.save(str(pdf))
    prof = profile_pdf(str(pdf))
    assert prof["mode"] == "scanned"
    assert prof["bottleneck"] == "ocr"
    assert prof["ocr_needed"] is True


def test_parallel_recommended_for_large_scanned(tmp_path):
    doc = _scanned_pdf(40)
    pdf = tmp_path / "big_scanned.pdf"
    doc.save(str(pdf))
    prof = profile_pdf(str(pdf))
    assert prof["mode"] == "scanned"
    assert prof["parallel_recommended"] is True  # 扫描件 ≥30 页 → 建议并行
