"""Evidence-based semantic decisions for YOLO visual candidates."""

from __future__ import annotations

import fitz

from . import formulas
from .table_detect import is_graph_region, looks_like_table_data


def _image_coverage(page, rect: fitz.Rect) -> float:
    area = rect.get_area()
    if area <= 0:
        return 0.0
    covered = 0.0
    for image in page.get_images(full=True):
        for image_rect in page.get_image_rects(image[0]):
            covered += (fitz.Rect(image_rect) & rect).get_area()
    return round(min(1.0, covered / area), 3)


def find_nearby_caption(page, rect: list[float] | fitz.Rect) -> dict | None:
    """Find a caption immediately above/below a visual, not only inside its box."""
    region = fitz.Rect(*rect) if not isinstance(rect, fitz.Rect) else rect
    vertical_pad = min(90.0, page.rect.height * 0.15)
    search = fitz.Rect(
        max(page.rect.x0, region.x0 - 20),
        max(page.rect.y0, region.y0 - 35),
        min(page.rect.x1, region.x1 + 20),
        min(page.rect.y1, region.y1 + vertical_pad),
    )
    candidates = []
    for block in page.get_text("blocks"):
        if block[6] != 0 or not block[4].strip():
            continue
        block_rect = fitz.Rect(block[:4])
        if block_rect.intersects(search):
            kind = formulas.caption_kind(block[4])
            if kind:
                gap = min(abs(block_rect.y0 - region.y1), abs(region.y0 - block_rect.y1))
                candidates.append((gap, block_rect, block[4].strip(), kind))
    if not candidates:
        return None
    _, block_rect, text, kind = min(candidates, key=lambda item: item[0])
    return {"text": text, "kind": kind, "bbox_pdf": list(block_rect)}


def analyze_visual_region(page, rect: list[float], detector_class: str, drawings=None) -> dict:
    """Resolve ``figure``/``table`` hints using text, image, geometry and context."""
    region = fitz.Rect(*rect) & page.rect
    if region.is_empty:
        return {"semantic_class": "artifact", "reason": "empty_region", "evidence": {}}

    page_area = max(1.0, page.rect.get_area())
    area_ratio = region.get_area() / page_area
    in_margin = region.y1 <= page.rect.height * 0.10 or region.y0 >= page.rect.height * 0.90
    raw_text = page.get_text("text", clip=region).strip()
    image_coverage = _image_coverage(page, region)
    caption = find_nearby_caption(page, region)
    graph_like = is_graph_region(page, list(region), drawings=drawings)
    evidence = {
        "detector_class": detector_class,
        "image_coverage": image_coverage,
        "native_chars": len(raw_text),
        "graph_like": graph_like,
        "caption_kind": caption["kind"] if caption else None,
        "caption_bbox": caption["bbox_pdf"] if caption else None,
        "area_ratio": round(area_ratio, 4),
    }

    tiny = area_ratio < 0.006 or region.height < page.rect.height * 0.022
    if in_margin and tiny and image_coverage < 0.2:
        return {"semantic_class": "artifact", "reason": "small_margin_region", "evidence": evidence}
    if detector_class == "table" and caption and caption["kind"] == "table":
        return {"semantic_class": "table", "reason": "table_caption", "evidence": evidence, "caption": caption}
    if detector_class == "table" and looks_like_table_data(raw_text):
        return {"semantic_class": "table", "reason": "table_evidence", "evidence": evidence, "caption": caption}
    if detector_class == "figure" and raw_text and image_coverage < 0.05 and not graph_like:
        if area_ratio < 0.005:
            return {"semantic_class": "text", "reason": "tiny_text_region", "evidence": evidence}
    if len(raw_text) >= 80 and image_coverage < 0.45 and not graph_like:
        return {"semantic_class": "text", "reason": "text_dominant", "evidence": evidence}
    if detector_class == "figure" and len(raw_text) >= 30 and image_coverage < 0.05 and not graph_like:
        return {"semantic_class": "text", "reason": "text_only_figure", "evidence": evidence}
    if caption and caption["kind"] == "figure":
        return {"semantic_class": "image", "reason": "figure_caption", "evidence": evidence, "caption": caption}
    if detector_class == "table" and image_coverage >= 0.55 and not graph_like:
        # A raster-only table has no native text evidence. Preserve the detector
        # hint long enough for recognize_table() to try OCR/structure recovery;
        # the pipeline falls back to an image when recognition is inconclusive.
        return {"semantic_class": "table", "reason": "raster_table_candidate", "evidence": evidence, "caption": caption}
    if graph_like or image_coverage >= 0.55:
        reason = "raster_visual" if image_coverage >= 0.55 else "graph_geometry"
        return {"semantic_class": "image", "reason": reason, "evidence": evidence, "caption": caption}
    if detector_class == "figure":
        return {"semantic_class": "image", "reason": "detector_figure", "evidence": evidence, "caption": caption}
    return {"semantic_class": detector_class, "reason": "detector_fallback", "evidence": evidence, "caption": caption}
