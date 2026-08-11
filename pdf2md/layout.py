"""doclayout_yolo 版面检测 — 只给几何 + 弱类别提示, 语义决策交给 classify.py.

移植自 yunshu-litwise/tools/layout_converter.py Phase 1。
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from . import models as model_assets

MODEL_PATH = str(model_assets.model_path("layout"))

# The shipped DocLayout-YOLO checkpoint is executable PyTorch data.  The digest
# is part of the trust boundary and must change deliberately with the model.
DEFAULT_MODEL_SHA256 = model_assets.load_manifest().by_name("layout").sha256

# Model metadata is the source of truth.  Numeric ids are deliberately absent:
# a checkpoint may reorder ids while keeping stable class names.
_MODEL_CLASS_ALIASES = {
    "title": "title",
    "plain_text": "text",
    "text": "text",
    "abandon": "artifact",
    "figure": "figure",
    "figure_caption": "text",
    "table": "table",
    "table_caption": "text",
    "table_footnote": "text",
    "isolate_formula": "formula",
    "formula": "formula",
    "formula_caption": "text",
}

_VISUAL_IMAGE = {"figure", "table"}
_VISUAL_TEXT = {"text", "title", "abstract", "list", "reference"}

_model = None
_loaded_model_path: Path | None = None


def resolve_model_path(explicit: str | os.PathLike | None = None) -> Path:
    """Resolve explicit overrides before the verified Release installation path."""
    selected = explicit or os.environ.get("PDF2MD_LAYOUT_MODEL") or MODEL_PATH
    return Path(selected).expanduser().resolve()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def semantic_class(names: dict | list | tuple, class_id: int) -> str:
    """Translate a detector id through its own class-name metadata."""
    try:
        raw = names.get(class_id) if hasattr(names, "get") else names[class_id]
    except (IndexError, KeyError, TypeError):
        return "unknown"
    normalized = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    return _MODEL_CLASS_ALIASES.get(normalized, "unknown")


def model_class_name(names: dict | list | tuple, class_id: int) -> str:
    try:
        raw = names.get(class_id) if hasattr(names, "get") else names[class_id]
    except (IndexError, KeyError, TypeError):
        return "unknown"
    return str(raw or "unknown")


def preflight_layout_model(
    model_path: str | os.PathLike | None = None,
    *,
    expected_sha256: str | None = None,
) -> dict:
    """Require a pinned digest before an executable ``.pt`` is deserialized."""
    path = resolve_model_path(model_path)
    if not path.is_file():
        raise RuntimeError(
            f"model_missing:layout — layout model file not found: {path}. "
            "Run `python -m pdf2md.models install`, or set --layout-model with its digest."
        )
    actual = _sha256(path)
    expected = (expected_sha256 or os.environ.get("PDF2MD_LAYOUT_MODEL_SHA256") or "").strip().lower()
    if not expected and actual == DEFAULT_MODEL_SHA256:
        expected = DEFAULT_MODEL_SHA256
    if not expected:
        raise RuntimeError(
            "model_untrusted:layout — executable .pt weights require a pinned SHA-256. "
            "Pass --layout-model-sha256 or set PDF2MD_LAYOUT_MODEL_SHA256."
        )
    if len(expected) != 64 or any(ch not in "0123456789abcdef" for ch in expected):
        raise RuntimeError("model_untrusted:layout — expected SHA-256 must be 64 hexadecimal characters")
    if actual != expected:
        raise RuntimeError(
            f"model_integrity:layout — SHA-256 mismatch for {path}: expected {expected}, got {actual}"
        )
    return {
        "name": "doclayout_yolo", "path": str(path), "available": True,
        "verified": True, "sha256": actual,
    }



def merge_table_regions(regions: list[dict], gap: float = 20.0) -> list[dict]:
    """合并被 YOLO 切碎/重叠的 table 区域 (同一张表多个框 → 外接矩形).

    贪心: 相交或竖直相邻 (间隙 ≤ gap) 且水平重叠的 table 框并为一个。
    """
    tables = [r for r in regions if r["visual_class"] == "table"]
    others = [r for r in regions if r["visual_class"] != "table"]
    # A detector may emit one low-confidence container around several precise
    # table boxes.  The container is not a logical document unit; discard it
    # before merging so neighbouring tables remain independently extractable.
    precise: list[dict] = []
    for candidate in tables:
        box = candidate["bbox_pdf"]
        contained = [
            other for other in tables if other is not candidate
            and _overlap_fraction(other["bbox_pdf"], box) >= 0.8
            and _box_area(other["bbox_pdf"]) < _box_area(box) * 0.8
        ]
        if len(contained) >= 2:
            continue
        precise.append(candidate)
    tables = precise
    merged: list[dict] = []
    for t in sorted(tables, key=lambda r: (r["bbox_pdf"][1], r["bbox_pdf"][0])):
        for m in merged:
            if _boxes_overlap(t["bbox_pdf"], m["bbox_pdf"]):
                b = m["bbox_pdf"]
                tb = t["bbox_pdf"]
                m["bbox_pdf"] = [
                    min(b[0], tb[0]), min(b[1], tb[1]),
                    max(b[2], tb[2]), max(b[3], tb[3]),
                ]
                m["confidence"] = max(m.get("confidence") or 0.0, t.get("confidence") or 0.0)
                break
        else:
            merged.append(dict(t))
    return merged + others


def _boxes_overlap(a: list[float], b: list[float]) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def _get_model(
    model_path: str | os.PathLike | None = None,
    *,
    expected_sha256: str | None = None,
):
    global _model, _loaded_model_path
    path = resolve_model_path(model_path)
    if _model is None or _loaded_model_path != path:
        preflight_layout_model(path, expected_sha256=expected_sha256)
        # Ultralytics supports a restricted allow-list loader for official
        # checkpoints.  Enable it before importing the package.
        os.environ["ULTRALYTICS_SAFE_LOAD"] = "true"
        os.environ["YOLO_AUTOINSTALL"] = "false"
        from doclayout_yolo import YOLOv10  # noqa: PLC0415

        _model = YOLOv10(str(path))
        _loaded_model_path = path
    return _model


def detect_layout(pdf_path: str, *, conf: float = 0.25, dpi: int = 150,
                  max_pages: int | None = None, model_path: str | os.PathLike | None = None,
                  model_sha256: str | None = None) -> list[list[dict]]:
    """逐页 YOLO 检测。返回 list[page] -> list[Region dict]。

    Region: {"page": 1-based, "bbox_pdf": [x0,y0,x1,y1], "visual_class": str, "confidence": float}
    """
    import numpy as np  # noqa: PLC0415
    import fitz  # noqa: PLC0415

    model = _get_model(model_path, expected_sha256=model_sha256)
    doc = fitz.open(pdf_path)
    n_pages = len(doc) if max_pages is None else min(max_pages, len(doc))
    all_pages = []
    for page_num in range(n_pages):
        page = doc[page_num]
        pw, ph = page.rect.width, page.rect.height
        pix = page.get_pixmap(dpi=dpi)
        arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        if arr.shape[2] == 4:
            arr = arr[:, :, :3]
        results = model(arr, conf=conf, verbose=False)
        names = getattr(results[0], "names", None) or getattr(model, "names", {})
        img_h, img_w = arr.shape[:2]
        sx, sy = pw / img_w, ph / img_h
        regions = []
        if results[0].boxes is not None:
            for box in results[0].boxes:
                cls_id = int(box.cls[0])
                semantic = semantic_class(names, cls_id)
                raw_class = model_class_name(names, cls_id)
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                regions.append(
                    {
                        "page": page_num + 1,
                        "bbox_pdf": [x1 * sx, y1 * sy, x2 * sx, y2 * sy],
                        "visual_class": semantic,
                        "detector_class": semantic,
                        "model_class": raw_class,
                        "detector": "doclayout_yolo",
                        "confidence": float(box.conf[0]),
                    }
                )
        all_pages.append(suppress_overlapping_regions(merge_table_regions(regions)))
    doc.close()
    return all_pages


_TEXT_CLASSES = {"text", "title", "abstract", "list", "reference"}


def _box_area(box: list[float]) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _suppress_text_containers(regions: list[dict]) -> list[dict]:
    """Drop broad detector boxes when several local text boxes cover them."""
    text_regions = [r for r in regions if r.get("visual_class") in _TEXT_CLASSES]
    containers: set[int] = set()
    for parent in text_regions:
        parent_area = _box_area(parent["bbox_pdf"])
        if parent_area <= 0:
            continue
        children = [
            child for child in text_regions
            if child is not parent
            and _box_area(child["bbox_pdf"]) <= parent_area * 0.65
            and _overlap_fraction(child["bbox_pdf"], parent["bbox_pdf"]) >= 0.9
        ]
        covered_area = sum(_box_area(child["bbox_pdf"]) for child in children)
        if len(children) >= 2 and covered_area >= parent_area * 0.12:
            containers.add(id(parent))
    return [region for region in regions if id(region) not in containers]


def _suppress_formula_fragments(regions: list[dict]) -> list[dict]:
    """Keep one stacked-equation container instead of overlapping fragments."""
    formula_regions = [r for r in regions if r.get("visual_class") == "formula"]
    fragments: set[int] = set()
    for parent in formula_regions:
        parent_area = _box_area(parent["bbox_pdf"])
        if parent_area <= 0:
            continue
        children = [
            child for child in formula_regions
            if child is not parent
            and _box_area(child["bbox_pdf"]) <= parent_area * 0.8
            and _overlap_fraction(child["bbox_pdf"], parent["bbox_pdf"]) >= 0.9
        ]
        if len(children) >= 2:
            fragments.update(id(child) for child in children)
    return [region for region in regions if id(region) not in fragments]


def _overlap_fraction(a: list[float], b: list[float]) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    iw = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    ih = max(0.0, min(ay1, by1) - max(ay0, by0))
    inter = iw * ih
    amin = min(
        max(0.0, (ax1 - ax0) * (ay1 - ay0)),
        max(0.0, (bx1 - bx0) * (by1 - by0)),
    )
    return inter / amin if amin else 0.0


def suppress_overlapping_regions(regions: list[dict], threshold: float = 0.8) -> list[dict]:
    """Suppress duplicate detector boxes while retaining merged-label provenance."""
    regions = _suppress_formula_fragments(regions)
    regions = _suppress_text_containers(regions)
    ranked = sorted(regions, key=lambda r: float(r.get("confidence") or 0.0), reverse=True)
    kept: list[dict] = []
    for region in ranked:
        candidate = dict(region)
        candidate.setdefault("merged_detector_classes", [candidate.get("visual_class", "unknown")])
        duplicate = None
        for existing in kept:
            compatible = (
                candidate.get("visual_class") == existing.get("visual_class")
                or {candidate.get("visual_class"), existing.get("visual_class")} <= _TEXT_CLASSES
            )
            candidate_area = _box_area(candidate["bbox_pdf"])
            existing_area = _box_area(existing["bbox_pdf"])
            area_similarity = min(candidate_area, existing_area) / max(candidate_area, existing_area, 1.0)
            if compatible and area_similarity >= 0.67 \
                    and _overlap_fraction(candidate["bbox_pdf"], existing["bbox_pdf"]) >= threshold:
                duplicate = existing
                break
        if duplicate is None:
            kept.append(candidate)
            continue
        merged = set(duplicate.get("merged_detector_classes", []))
        merged.update(candidate.get("merged_detector_classes", []))
        duplicate["merged_detector_classes"] = sorted(merged)
    return sorted(kept, key=lambda r: (r["bbox_pdf"][1], r["bbox_pdf"][0]))
