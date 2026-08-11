"""RapidOCR 封装 — 复用 litwise-ocr vendored 适配器 (onnxruntime CPU, 完全离线)。

镜像 tools/ocr_worker.py::_run_rapidocr 的加载方式与 API 用法。
"""

from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from . import models as model_assets

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ADAPTER = Path(
    os.environ.get(
        "LITWISE_RAPIDOCR_ADAPTER",
        _REPO_ROOT / "models" / "production" / "rapidocr-adapter",
    )
).resolve()

_engine = None

_manifest = model_assets.load_manifest()
_MODEL_SHA256 = {
    "ch_PP-OCRv4_det_infer.onnx": _manifest.by_name("rapidocr_det").sha256,
    "ch_PP-OCRv4_rec_infer.onnx": _manifest.by_name("rapidocr_rec").sha256,
    "ch_ppocr_mobile_v2.0_cls_infer.onnx": _manifest.by_name("rapidocr_cls").sha256,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def adapter_status() -> dict:
    path = (_ADAPTER / "rapidocr").resolve()
    model_dir = path / "models"
    missing = [name for name in _MODEL_SHA256 if not (model_dir / name).is_file()]
    available = path.is_dir() and not missing
    result = {"available": available, "path": str(path)}
    if not available:
        result["error"] = f"model_missing:rapidocr — required files under {model_dir}"
        return result
    for name, expected in _MODEL_SHA256.items():
        actual = _sha256(model_dir / name)
        if actual != expected:
            return {
                "available": False,
                "path": str(path),
                "error": f"model_integrity:rapidocr — SHA-256 mismatch: {name}",
                "model": name,
                "sha256": actual,
                "expected_sha256": expected,
            }
    result["verified"] = True
    return result


def _get_engine():
    global _engine
    if _engine is None:
        status = adapter_status()
        if not status.get("available"):
            raise RuntimeError(status.get("error") or "model_missing:rapidocr")
        if str(_ADAPTER) not in sys.path:
            sys.path.insert(0, str(_ADAPTER))
        from rapidocr import RapidOCR  # noqa: PLC0415

        _engine = RapidOCR()
    return _engine


@dataclass
class OCRLine:
    """一条 OCR 结果: 文本 + PDF 坐标框 (x0,y0,x1,y1) + 置信度."""

    text: str
    box_pdf: tuple[float, float, float, float]
    confidence: float


def ocr_image(png_bytes: bytes) -> list[tuple[str, float]]:
    """对一张 PNG 做 OCR, 返回 [(text, confidence), ...] 逐行."""
    output = _get_engine()(png_bytes)
    texts = list(output.txts or ())
    scores = [float(v) for v in (output.scores or ())]
    return [(t.strip(), s) for t, s in zip(texts, scores) if t and t.strip()]


def _box_px_to_pdf(box_px, rect_tl, scale: float) -> tuple[float, float, float, float]:
    """OCR 检测框 (原图像素四边形) → PDF 坐标 (x0,y0,x1,y1).

    rect_tl 为区域左上角 (fitz.Rect 或 Point, 均支持下标访问).
    """
    xs = [pt[0] for pt in box_px]
    ys = [pt[1] for pt in box_px]
    rx0, ry0 = rect_tl[0], rect_tl[1]
    return (
        rx0 + min(xs) / scale,
        ry0 + min(ys) / scale,
        rx0 + max(xs) / scale,
        ry0 + max(ys) / scale,
    )


def ocr_region_with_boxes(page, rect, dpi: int = 300) -> list[OCRLine]:
    """把页面区域渲染成 PNG 再 OCR, 返回带 PDF 坐标框的逐行结果.

    rect 为 PDF 坐标 [x0,y0,x1,y1]; 框由原图像素按 dpi/72 缩放 + 区域偏移换算回 PDF 点。
    """
    import fitz  # noqa: PLC0415

    rect = fitz.Rect(*rect) & page.rect
    if rect.is_empty:
        return []
    scale = max(1.0, float(dpi) / 72.0)
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
    output = _get_engine()(pix.tobytes("png"))
    lines: list[OCRLine] = []
    boxes = output.boxes if output.boxes is not None else ()
    for txt, box, score in zip(output.txts or (), boxes, output.scores or ()):
        t = str(txt).strip()
        if not t:
            continue
        b = _box_px_to_pdf(box, rect, scale)
        lines.append(OCRLine(t, b, float(score)))
    return lines


def ocr_region(page, rect, dpi: int = 300) -> list[tuple[str, float]]:
    """把页面区域渲染成 PNG 再 OCR. rect 为 PDF 坐标 [x0,y0,x1,y1]."""
    return [(line.text, line.confidence) for line in ocr_region_with_boxes(page, rect, dpi)]
