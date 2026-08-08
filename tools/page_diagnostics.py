"""Deterministic page diagnostics that decide whether OCR is required."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import unicodedata

import fitz


@dataclass(frozen=True)
class DiagnosticPolicy:
    min_native_characters: int = 400
    min_valid_character_ratio: float = 0.97
    max_replacement_ratio: float = 0.002
    max_control_character_ratio: float = 0.002
    max_overlap_ratio: float = 0.08


@dataclass
class PageSignals:
    page: int
    width: float
    height: float
    native_characters: int
    valid_character_ratio: float
    replacement_ratio: float
    control_character_ratio: float
    text_coverage: float
    overlap_ratio: float
    image_coverage: float
    block_count: int
    crossed_reading_edges: int
    suspicious_regions: list[list[float]] = field(default_factory=list)
    column_count: int = 1
    native_elements: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class PageDiagnostic:
    page: int
    status: str
    reasons: list[str]
    repair_regions: list[list[float]]
    metrics: dict[str, float]


def diagnose_page(signals: PageSignals, policy: DiagnosticPolicy | None = None) -> PageDiagnostic:
    policy = policy or DiagnosticPolicy()
    reasons = []
    if signals.native_characters < policy.min_native_characters or signals.valid_character_ratio < policy.min_valid_character_ratio:
        reasons.append("low_native_retention")
    if signals.replacement_ratio > policy.max_replacement_ratio:
        reasons.append("replacement_characters")
    if signals.control_character_ratio > policy.max_control_character_ratio:
        reasons.append("control_characters")
    if signals.overlap_ratio > policy.max_overlap_ratio:
        reasons.append("overlapping_text_blocks")
    if signals.crossed_reading_edges:
        reasons.append("reading_order_crossing")
    text_damage = any(reason in {
        "low_native_retention", "replacement_characters", "control_characters"
    } for reason in reasons)
    if not text_damage:
        status = "native_pass"
        repair_regions = []
    elif signals.suspicious_regions:
        status = "ocr_required"
        repair_regions = signals.suspicious_regions
    elif signals.image_coverage >= 0.5 or signals.native_characters < policy.min_native_characters:
        status = "ocr_required"
        repair_regions = [[0.0, 0.0, signals.width, signals.height]]
    else:
        status = "manual_review"
        repair_regions = []
    return PageDiagnostic(
        signals.page, status, reasons, repair_regions,
        {
            "native_characters": float(signals.native_characters),
            "valid_character_ratio": signals.valid_character_ratio,
            "replacement_ratio": signals.replacement_ratio,
            "control_character_ratio": signals.control_character_ratio,
            "text_coverage": signals.text_coverage,
            "overlap_ratio": signals.overlap_ratio,
            "image_coverage": signals.image_coverage,
            "crossed_reading_edges": float(signals.crossed_reading_edges),
            "column_count": float(signals.column_count),
        },
    )


def extract_page_signals(pdf_path: str | Path) -> list[PageSignals]:
    document = fitz.open(str(pdf_path))
    results = []
    try:
        for page_index, page in enumerate(document):
            raw = page.get_text("rawdict")
            elements = _native_elements(raw, page.rect)
            text = "".join(item["text"] for item in elements)
            text_boxes = [item["bbox_pdf"] for item in elements]
            image_boxes = [
                [float(value) for value in block.get("bbox", (0, 0, 0, 0))]
                for block in raw.get("blocks", []) if block.get("type") == 1
            ]
            page_area = max(float(page.rect.width * page.rect.height), 1.0)
            columns = _column_hints(text_boxes, float(page.rect.width))
            for item, column in zip(elements, columns):
                item["column_hint"] = column
            char_count = len(text)
            replacement = text.count("\ufffd")
            controls = sum(unicodedata.category(character) == "Cc" and character not in "\n\r\t" for character in text)
            valid = sum(_valid_character(character) for character in text)
            overlap_ratio = _overlap_ratio(text_boxes)
            results.append(PageSignals(
                page=page_index + 1,
                width=float(page.rect.width),
                height=float(page.rect.height),
                native_characters=char_count,
                valid_character_ratio=valid / max(char_count, 1),
                replacement_ratio=replacement / max(char_count, 1),
                control_character_ratio=controls / max(char_count, 1),
                text_coverage=min(1.0, sum(_area(box) for box in text_boxes) / page_area),
                overlap_ratio=overlap_ratio,
                image_coverage=min(1.0, sum(_area(box) for box in image_boxes) / page_area),
                block_count=len(text_boxes),
                crossed_reading_edges=_crossed_edges(text_boxes, columns),
                suspicious_regions=_suspicious_regions(elements),
                column_count=max(columns, default=0) + 1 if elements else 1,
                native_elements=elements,
            ))
    finally:
        document.close()
    return results


def _native_elements(raw: dict, page_rect) -> list[dict]:
    elements = []
    for block in raw.get("blocks", []):
        if block.get("type") != 0:
            continue
        lines = block.get("lines") or []
        text_parts = []
        fonts, sizes, colors = [], [], []
        for line in lines:
            for span in line.get("spans") or []:
                chars = span.get("chars") or []
                value = "".join(character.get("c", "") for character in chars) or span.get("text", "")
                text_parts.append(value)
                fonts.append(str(span.get("font") or ""))
                sizes.append(float(span.get("size") or 0.0))
                colors.append(int(span.get("color") or 0))
        text = "\n".join(part for part in text_parts if part).strip()
        if not text:
            continue
        raw_bbox = fitz.Rect(*block.get("bbox", (0, 0, 0, 0))) & page_rect
        bbox = [round(float(value), 3) for value in (raw_bbox.x0, raw_bbox.y0, raw_bbox.x1, raw_bbox.y1)]
        elements.append({
            "type": "text",
            "text": text,
            "bbox_pdf": bbox,
            "bbox_normalized": [
                round(bbox[0] / page_rect.width, 6), round(bbox[1] / page_rect.height, 6),
                round(bbox[2] / page_rect.width, 6), round(bbox[3] / page_rect.height, 6),
            ],
            "font_name": max(fonts, key=fonts.count) if fonts else "",
            "font_size": round(max(sizes, default=0.0), 3),
            "color": colors[0] if colors else 0,
            "rotation": 0,
            "line_count": len(lines),
            "column_hint": 0,
            "source": "native_text",
        })
    return elements


def _column_hints(boxes: list[list[float]], page_width: float) -> list[int]:
    if len(boxes) < 2:
        return [0] * len(boxes)
    centers = [(box[0] + box[2]) / 2 for box in boxes]
    left = [center for center in centers if center < page_width * 0.48]
    right = [center for center in centers if center > page_width * 0.52]
    if left and right:
        return [0 if center < page_width / 2 else 1 for center in centers]
    return [0] * len(boxes)


def _crossed_edges(boxes: list[list[float]], columns: list[int]) -> int:
    crossings = 0
    for index in range(1, len(boxes)):
        if columns[index] == columns[index - 1] and boxes[index][1] + 1 < boxes[index - 1][1]:
            crossings += 1
    return crossings


def _overlap_ratio(boxes: list[list[float]]) -> float:
    total = sum(_area(box) for box in boxes)
    if total <= 0:
        return 0.0
    overlap = 0.0
    for index, left in enumerate(boxes):
        for right in boxes[index + 1:]:
            overlap += _intersection(left, right)
    return min(1.0, overlap / total)


def _suspicious_regions(elements: list[dict]) -> list[list[float]]:
    result = []
    for item in elements:
        text = item["text"]
        if "\ufffd" in text or any(unicodedata.category(character) == "Cc" for character in text):
            result.append(item["bbox_pdf"])
    return result


def _valid_character(character: str) -> bool:
    category = unicodedata.category(character)
    return character in "\n\r\t" or not category.startswith("C")


def _area(box: list[float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _intersection(left: list[float], right: list[float]) -> float:
    width = max(0.0, min(left[2], right[2]) - max(left[0], right[0]))
    height = max(0.0, min(left[3], right[3]) - max(left[1], right[1]))
    return width * height
