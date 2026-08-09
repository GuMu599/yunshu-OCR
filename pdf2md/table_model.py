"""SLANet 表格结构引擎 (vendored rapid_table) — 镜像 FormulaModel 的「缺失/失败 → 回退」模式.

结构模型 (slanet_plus onnx ~7.8MB) 输出 HTML (含 rowspan/colspan) + 单元格框;
cell 文字由 RapidTable 内部用 vendored RapidOCR 识别 (与 pdf2md/ocr.py 同引擎)。
权重在 models/production/table-adapter/rapid_table/models/ 下 (vendored, 离线)。
权重缺失或推理失败 → available() False / structure_table 返回 None → 调用方
(recognize_table) 回退几何重建或图片兜底, 绝不抛错硬猜。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

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
            if not (_ADAPTER / "rapid_table").is_dir():
                cls._failed = True
                cls._error = "model_missing:table — vendored table adapter not found"
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
