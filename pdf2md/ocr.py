"""RapidOCR 封装 — 复用 litwise-ocr vendored 适配器 (onnxruntime CPU, 完全离线)。

镜像 tools/ocr_worker.py::_run_rapidocr 的加载方式与 API 用法。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ADAPTER = Path(
    os.environ.get(
        "LITWISE_RAPIDOCR_ADAPTER",
        _REPO_ROOT / "models" / "production" / "rapidocr-adapter",
    )
).resolve()

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        if not (_ADAPTER / "rapidocr").is_dir():
            raise RuntimeError("model_missing:rapidocr — vendored RapidOCR adapter not found")
        if str(_ADAPTER) not in sys.path:
            sys.path.insert(0, str(_ADAPTER))
        from rapidocr import RapidOCR  # noqa: PLC0415

        _engine = RapidOCR()
    return _engine


def ocr_image(png_bytes: bytes) -> list[tuple[str, float]]:
    """对一张 PNG 做 OCR, 返回 [(text, confidence), ...] 逐行."""
    output = _get_engine()(png_bytes)
    texts = list(output.txts or ())
    scores = [float(v) for v in (output.scores or ())]
    return [(t.strip(), s) for t, s in zip(texts, scores) if t and t.strip()]


def ocr_region(page, rect, dpi: int = 300) -> list[tuple[str, float]]:
    """把页面区域渲染成 PNG 再 OCR. rect 为 PDF 坐标 [x0,y0,x1,y1]."""
    import fitz  # noqa: PLC0415

    rect = fitz.Rect(*rect) & page.rect
    if rect.is_empty:
        return []
    scale = max(1.0, float(dpi) / 72.0)
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
    return ocr_image(pix.tobytes("png"))
