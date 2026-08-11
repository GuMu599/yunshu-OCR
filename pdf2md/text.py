"""PyMuPDF 文字/图片提取 — 每个版面区域读原生文字; figure/降级区域存图片.

移植自 yunshu-litwise/tools/layout_converter.py Phase 2。
"""

from __future__ import annotations

import os


def _vertical_overlap_fraction(a, b) -> float:
    overlap = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    min_height = max(1.0, min(a[3] - a[1], b[3] - b[1]))
    return overlap / min_height


def _merge_visual_rows(lines: list[tuple[list[float], str]]) -> list[tuple[list[float], str]]:
    """Merge PDF text fragments that share one visible baseline.

    PDFs commonly expose superscripts and mixed-font fragments as separate
    logical lines. Their bounding boxes still overlap vertically, so grouping
    by that overlap and then sorting by x restores the visible reading order.
    """
    rows: list[dict] = []
    for bbox, text in sorted(lines, key=lambda item: ((item[0][1] + item[0][3]) / 2, item[0][0])):
        matching = [
            row for row in rows
            if _vertical_overlap_fraction(bbox, row["bbox"]) >= 0.45
        ]
        if not matching:
            rows.append({"bbox": list(bbox), "parts": [(bbox, text)]})
            continue
        row = max(matching, key=lambda candidate: _vertical_overlap_fraction(bbox, candidate["bbox"]))
        row["parts"].append((bbox, text))
        row["bbox"] = [
            min(row["bbox"][0], bbox[0]), min(row["bbox"][1], bbox[1]),
            max(row["bbox"][2], bbox[2]), max(row["bbox"][3], bbox[3]),
        ]

    merged = []
    for row in rows:
        parts = sorted(row["parts"], key=lambda item: item[0][0])
        chunks: list[str] = []
        previous_bbox = None
        for bbox, text in parts:
            if previous_bbox is not None:
                gap = bbox[0] - previous_bbox[2]
                min_height = min(
                    previous_bbox[3] - previous_bbox[1], bbox[3] - bbox[1]
                )
                if gap > max(2.0, min_height * 0.35) \
                        and not chunks[-1].endswith(" ") and not text.startswith(" "):
                    chunks.append(" ")
            chunks.append(text)
            previous_bbox = bbox
        merged.append((row["bbox"], "".join(chunks)))
    return sorted(merged, key=lambda item: (item[0][1], item[0][0]))


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
    try:
        text, _ = _region_text_ordered_impl(page, rect, gutter_mid, [])
        return text
    except Exception:
        return ""


def _bbox_center_inside_any(bbox, rects) -> bool:
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    return any(r[0] <= cx <= r[2] and r[1] <= cy <= r[3] for r in rects)


def _char_run(chars: list[dict]) -> tuple[list[float], str]:
    boxes = [char["bbox"] for char in chars]
    return (
        [
            min(box[0] for box in boxes), min(box[1] for box in boxes),
            max(box[2] for box in boxes), max(box[3] for box in boxes),
        ],
        "".join(char.get("c", "") for char in chars),
    )


def _region_text_ordered_impl(page, rect, gutter_mid, excluded_rects):
    import fitz  # noqa: PLC0415

    r = fitz.Rect(*rect) & page.rect
    exclusions = [list(fitz.Rect(*box) & page.rect) for box in excluded_rects]
    mode = "rawdict" if exclusions else "dict"
    data = page.get_text(mode, clip=r)
    lines: list[tuple[list[float], str]] = []
    excluded_chars = 0
    for block in data.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            if not exclusions:
                text = "".join(
                    span.get("text", "") for span in line.get("spans", [])
                ).strip()
                if text:
                    lines.append((line["bbox"], text))
                continue

            for span in line.get("spans", []):
                run: list[dict] = []
                for char in span.get("chars", []):
                    if not _bbox_center_inside_any(char["bbox"], [list(r)]):
                        if run:
                            lines.append(_char_run(run))
                            run = []
                        continue
                    if _bbox_center_inside_any(char["bbox"], exclusions):
                        if char.get("c", "").strip():
                            excluded_chars += 1
                        if run:
                            lines.append(_char_run(run))
                            run = []
                        continue
                    run.append(char)
                if run:
                    lines.append(_char_run(run))
    if not lines:
        return "", excluded_chars

    lines = _merge_visual_rows(lines)
    crosses_gutter = (
        gutter_mid is not None
        and r.x0 < gutter_mid < r.x1
        and r.width >= page.rect.width * 0.6
    )
    if not crosses_gutter and gutter_mid is not None:
        left = [(bb, text) for bb, text in lines if (bb[0] + bb[2]) / 2 < gutter_mid]
        right = [(bb, text) for bb, text in lines if (bb[0] + bb[2]) / 2 >= gutter_mid]
        left.sort(key=lambda item: (item[0][1], item[0][0]))
        right.sort(key=lambda item: (item[0][1], item[0][0]))
        lines = left + right
    else:
        lines.sort(key=lambda item: (item[0][1], item[0][0]))
    return "\n".join(text for _, text in lines), excluded_chars


def region_text_ordered_excluding(page, rect, excluded_rects, gutter_mid=None):
    """Return ordered native text outside accepted formula boxes.

    ``None`` means extraction failed, allowing callers to preserve the original
    text instead of turning a diagnostic failure into content loss.
    """
    try:
        return _region_text_ordered_impl(page, rect, gutter_mid, excluded_rects)
    except Exception:
        return None


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
