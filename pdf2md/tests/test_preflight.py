"""Layout model configuration is explicit and validated before conversion."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md import layout  # noqa: E402


def test_explicit_model_path_has_priority(tmp_path, monkeypatch):
    env_path = tmp_path / "env.pt"
    monkeypatch.setenv("PDF2MD_LAYOUT_MODEL", str(env_path))
    explicit = tmp_path / "explicit.pt"
    assert layout.resolve_model_path(explicit) == explicit.resolve()


def test_environment_model_path_is_supported(tmp_path, monkeypatch):
    env_path = tmp_path / "model.pt"
    monkeypatch.setenv("PDF2MD_LAYOUT_MODEL", str(env_path))
    assert layout.resolve_model_path() == env_path.resolve()


def test_missing_layout_model_has_actionable_preflight_error(tmp_path):
    missing = tmp_path / "missing.pt"
    with pytest.raises(RuntimeError, match=r"model_missing:layout.*missing\.pt"):
        layout.preflight_layout_model(missing)


def test_preflight_checks_required_local_adapter_files(tmp_path, monkeypatch):
    adapter = tmp_path / "ocr"
    models = adapter / "rapidocr" / "models"
    models.mkdir(parents=True)
    monkeypatch.setattr("pdf2md.ocr._ADAPTER", adapter)
    status = __import__("pdf2md.ocr", fromlist=["adapter_status"]).adapter_status()
    assert status["available"] is False
    assert "model_missing:rapidocr" in status["error"]


def test_preflight_rejects_tampered_rapidocr_weights(tmp_path, monkeypatch):
    adapter = tmp_path / "ocr"
    models = adapter / "rapidocr" / "models"
    models.mkdir(parents=True)
    for name in (
        "ch_PP-OCRv4_det_infer.onnx",
        "ch_PP-OCRv4_rec_infer.onnx",
        "ch_ppocr_mobile_v2.0_cls_infer.onnx",
    ):
        (models / name).write_bytes(b"tampered")
    monkeypatch.setattr("pdf2md.ocr._ADAPTER", adapter)

    status = __import__("pdf2md.ocr", fromlist=["adapter_status"]).adapter_status()
    assert status["available"] is False
    assert "model_integrity:rapidocr" in status["error"]


def test_preflight_rejects_tampered_table_weights(tmp_path, monkeypatch):
    adapter = tmp_path / "table"
    models = adapter / "rapid_table" / "models"
    models.mkdir(parents=True)
    (models / "slanet-plus.onnx").write_bytes(b"tampered")
    monkeypatch.setattr("pdf2md.table_model._ADAPTER", adapter)

    status = __import__("pdf2md.table_model", fromlist=["adapter_status"]).adapter_status()
    assert status["available"] is False
    assert "model_integrity:table" in status["error"]
