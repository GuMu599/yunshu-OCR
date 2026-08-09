"""PDF 预检档案 — 判断 PDF 类型 (原生/扫描/混合), 预估耗时瓶颈与优化建议.

自动决定: 纯原生文字 PDF → 不需要 OCR (瓶颈在 YOLO 版面);
扫描件 → OCR 为主 (大文档建议进程级并行);
公式密度高 → pix2tex 值得加载。档案写入 report.json, 供用户与 AI 技能查看。
"""

from __future__ import annotations

import fitz

TEXT_PAGE_CHARS = 400      # 一页 >400 字符算"有文字页"
IMAGE_COVERAGE = 0.15      # 图片覆盖 >15% 算"图片页"
MATH_LINE_FRAC = 0.10      # 含数学符号行占比 > 该值 → 公式密集


def _sample_indices(n: int, max_pages: int) -> list[int]:
    if n <= max_pages:
        return list(range(n))
    stride = n / max_pages
    return [int(i * stride) for i in range(max_pages)]


def _page_metrics(page) -> dict:
    text = page.get_text("text").strip()
    img_area = 0.0
    page_area = page.rect.width * page.rect.height
    for img in page.get_images(full=True):
        for r in page.get_image_rects(img[0]):
            img_area += (r & page.rect).get_area()
    img_cov = min(1.0, img_area / page_area) if page_area else 0.0
    return {"chars": len(text), "image_coverage": img_cov}


def profile_pdf(pdf_path: str, *, max_pages: int = 8) -> dict:
    """预检 PDF → 档案 dict (模式/瓶颈/建议). 采样 ≤ max_pages 页, 廉价."""
    doc = fitz.open(pdf_path)
    n = len(doc)
    pages = _sample_indices(n, max_pages)
    text_pages = image_pages = math_lines = total_lines = 0
    for pno in pages:
        page = doc[pno]
        m = _page_metrics(page)
        if m["chars"] > TEXT_PAGE_CHARS:
            text_pages += 1
        if m["image_coverage"] > IMAGE_COVERAGE:
            image_pages += 1
        for line in page.get_text("text").splitlines():
            total_lines += 1
            if "=" in line or "\\" in line or "_" in line or "^" in line:
                math_lines += 1
    doc.close()

    sampled = max(1, len(pages))
    text_ratio = text_pages / sampled
    image_ratio = image_pages / sampled
    math_ratio = math_lines / max(1, total_lines)

    # 判型以原生文字可提取性为主: 图多的原生文字论文不应判扫描件 (图≠扫描)
    if text_ratio >= 0.6:
        mode = "native"
    elif text_ratio < 0.4:
        mode = "scanned"
    else:
        mode = "mixed"

    if mode == "scanned":
        bottleneck = "ocr"        # 每页 OCR 6-8s 为主
    elif math_ratio > MATH_LINE_FRAC:
        bottleneck = "formula"    # 公式密集 → pix2tex
    else:
        bottleneck = "layout"     # 原生文字 → YOLO 版面为主

    return {
        "mode": mode,
        "page_count": n,
        "sampled_pages": len(pages),
        "text_pages_ratio": round(text_ratio, 2),
        "image_pages_ratio": round(image_ratio, 2),
        "formula_density": round(math_ratio, 3),
        "bottleneck": bottleneck,
        "ocr_needed": mode in ("scanned", "mixed"),
        "parallel_recommended": mode == "scanned" and n >= 30,
    }
