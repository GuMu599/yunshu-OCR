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


def region_text_ordered(page, rect, gutter_mid=None) -> str:
    """区域内原生文字, 按栏感知阅读顺序 (左栏读完再右栏) 重排行序.

    PyMuPDF 会把同 y 的左右栏文字合并进同一 block (无法切分); 改用行级
    (get_text("dict") 每行有 bbox), 按行中心与 gutter_mid 分栏后重排。
    """
    import fitz  # noqa: PLC0415

    try:
        r = fitz.Rect(*rect) & page.rect
        d = page.get_text("dict", clip=r)
        lines: list[tuple[list[float], str]] = []
        for block in d.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                bbox = line["bbox"]
                text = "".join(span.get("text", "") for span in line.get("spans", [])).strip()
                if text:
                    lines.append((bbox, text))
        if not lines:
            return ""
        if gutter_mid is not None:
            left = [(bb, t) for bb, t in lines if (bb[0] + bb[2]) / 2 < gutter_mid]
            right = [(bb, t) for bb, t in lines if (bb[0] + bb[2]) / 2 >= gutter_mid]
            left.sort(key=lambda x: (x[0][1], x[0][0]))
            right.sort(key=lambda x: (x[0][1], x[0][0]))
            lines = left + right
        else:
            lines.sort(key=lambda x: (x[0][1], x[0][0]))
        return "\n".join(t for _, t in lines)
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
