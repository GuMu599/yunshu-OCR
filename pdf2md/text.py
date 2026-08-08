"""PyMuPDF 文字/图片提取 — 每个版面区域读原生文字; figure/降级区域存图片.

移植自 yunshu-litwise/tools/layout_converter.py Phase 2。
"""

from __future__ import annotations

import os


def region_text(page, rect) -> str:
    """clip 矩形区域内原生文字, 去首尾空白."""
    try:
        return page.get_text("text", clip=rect).strip()
    except Exception:
        return ""


def save_image(page, rect, images_dir: str, name: str, dpi: int = 200) -> str | None:
    """把区域渲染成 PNG 存到 images_dir, 返回相对链接 images/<name> 或 None."""
    import fitz  # noqa: PLC0415

    rect = fitz.Rect(*rect) & page.rect
    if rect.is_empty:
        return None
    try:
        os.makedirs(images_dir, exist_ok=True)
        pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), clip=rect, alpha=False)
        pix.save(os.path.join(images_dir, name))
        return f"images/{name}"
    except Exception:
        return None
