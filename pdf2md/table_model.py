"""SLANet 表格结构引擎 (vendored rapid_table) — 镜像 FormulaModel 的「缺失/失败 → 回退」模式.

结构模型 (slanet_plus onnx ~7.8MB) 输出 HTML (含 rowspan/colspan) + 单元格框;
cell 文字由 RapidTable 内部用 vendored RapidOCR 识别 (与 pdf2md/ocr.py 同引擎)。
权重在 models/production/table-adapter/rapid_table/models/ 下 (vendored, 离线)。
权重缺失或推理失败 → available() False / structure_table 返回 None → 调用方
(recognize_table) 回退几何重建或图片兜底, 绝不抛错硬猜。
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

from . import models as model_assets

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ADAPTER = Path(
    os.environ.get(
        "LITWISE_TABLE_ADAPTER",
        _REPO_ROOT / "models" / "production" / "table-adapter",
    )
).resolve()
_OCR_ADAPTER = Path(
    os.environ.get(
        "LITWISE_RAPIDOCR_ADAPTER",
        _REPO_ROOT / "models" / "production" / "rapidocr-adapter",
    )
).resolve()

_SLANET_SHA256 = model_assets.load_manifest().by_name("rapidtable").sha256


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def adapter_status() -> dict:
    path = (_ADAPTER / "rapid_table").resolve()
    weights = path / "models" / "slanet-plus.onnx"
    available = path.is_dir() and weights.is_file()
    result = {"available": available, "path": str(path)}
    if not available:
        result["error"] = f"model_missing:table — required weights: {weights}"
        return result
    actual = _sha256(weights)
    if actual != _SLANET_SHA256:
        return {
            "available": False,
            "path": str(path),
            "error": "model_integrity:table — SHA-256 mismatch: slanet-plus.onnx",
            "sha256": actual,
            "expected_sha256": _SLANET_SHA256,
        }
    result["verified"] = True
    return result


class TableModel:
    _engine = None
    _failed = False
    _error: str | None = None

    @classmethod
    def available(cls) -> bool:
        """适配器目录存在且未闩锁失败 → True."""
        if cls._failed:
            return False
        if cls._engine is not None:
            return True
        cls._ensure()
        return cls._engine is not None

    @classmethod
    def _ensure(cls) -> bool:
        if cls._failed:
            return False
        if cls._engine is None:
            status = adapter_status()
            if not status.get("available"):
                cls._failed = True
                cls._error = status.get("error") or "model_missing:table"
                return False
            if str(_ADAPTER) not in sys.path:
                sys.path.insert(0, str(_ADAPTER))
            # 让 RapidTable 内部能 import 到 vendored RapidOCR (cell 文字识别)
            if str(_OCR_ADAPTER) not in sys.path:
                sys.path.insert(0, str(_OCR_ADAPTER))
            try:
                from rapid_table import ModelType, RapidTable, RapidTableInput  # noqa: PLC0415

                cls._engine = RapidTable(RapidTableInput(model_type=ModelType.SLANETPLUS, use_ocr=True))
            except Exception as exc:  # noqa: BLE001
                cls._failed = True
                cls._error = f"model_missing:table — {exc}"
                return False
        return True

    @classmethod
    def structure_table(cls, png_bytes: bytes) -> tuple | None:
        """表格 PNG → (html, cell_boxes_px) | None. 失败返回 None 不抛错."""
        if not cls.available():
            return None
        try:
            result = cls._engine(png_bytes)
            htmls = result.pred_htmls or []
            if not htmls:
                return None
            cell_boxes = result.cell_bboxes[0] if result.cell_bboxes else None
            return htmls[0], cell_boxes
        except Exception:  # noqa: BLE001
            cls._failed = True
            cls._error = "table_failed"
            return None

    @classmethod
    def error(cls) -> str | None:
        return cls._error
