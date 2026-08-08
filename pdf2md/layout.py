"""doclayout_yolo 版面检测 — 只给几何 + 弱类别提示, 语义决策交给 classify.py.

移植自 yunshu-litwise/tools/layout_converter.py Phase 1。
"""

from __future__ import annotations

import os
from pathlib import Path

MODEL_PATH = os.path.join(
    os.environ.get("USERPROFILE", "C:/Users/GuMu"),
    r"AppData\Local\datalab\datalab\Cache\models\Layout\YOLO",
    "doclayout_yolo_docstructbench_imgsz1280_2501.pt",
)

# YOLO 类别只作弱提示, 不作决策
_YOLO_CLASS = {
    0: "text",
    1: "title",
    2: "figure",
    3: "table",
    4: "formula",
    5: "list",
    6: "reference",
    7: "abstract",
}

_VISUAL_IMAGE = {"figure", "table"}
_VISUAL_TEXT = {"text", "title", "abstract", "list", "reference"}

_model = None


def _get_model():
    global _model
    if _model is None:
        if not Path(MODEL_PATH).exists():
            raise RuntimeError(f"doclayout_yolo model not found: {MODEL_PATH}")
        from doclayout_yolo import YOLOv10  # noqa: PLC0415

        _model = YOLOv10(MODEL_PATH)
    return _model


def detect_layout(pdf_path: str, *, conf: float = 0.25, dpi: int = 150, max_pages: int | None = None) -> list[list[dict]]:
    """逐页 YOLO 检测。返回 list[page] -> list[Region dict]。

    Region: {"page": 1-based, "bbox_pdf": [x0,y0,x1,y1], "visual_class": str, "confidence": float}
    """
    import numpy as np  # noqa: PLC0415
    import fitz  # noqa: PLC0415

    model = _get_model()
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
        img_h, img_w = arr.shape[:2]
        sx, sy = pw / img_w, ph / img_h
        regions = []
        if results[0].boxes is not None:
            for box in results[0].boxes:
                cls_id = int(box.cls[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                regions.append(
                    {
                        "page": page_num + 1,
                        "bbox_pdf": [x1 * sx, y1 * sy, x2 * sx, y2 * sy],
                        "visual_class": _YOLO_CLASS.get(cls_id, "unknown"),
                        "confidence": float(box.conf[0]),
                    }
                )
        all_pages.append(regions)
    doc.close()
    return all_pages
