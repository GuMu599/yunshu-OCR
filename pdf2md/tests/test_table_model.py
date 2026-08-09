"""结构模型适配器: 权重缺失 → model_missing 优雅回退 (不依赖权重在 CI 存在)"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md import table_model  # noqa: E402


def _reset_model():
    table_model.TableModel._engine = None
    table_model.TableModel._failed = False
    table_model.TableModel._error = None


def test_model_missing_adapter_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(table_model, "_ADAPTER", tmp_path / "missing")
    _reset_model()
    assert table_model.TableModel.available() is False
    assert table_model.TableModel.error() is not None
    assert "model_missing:table" in table_model.TableModel.error()
    # 缺失时 structure_table 返回 None 不抛错
    assert table_model.TableModel.structure_table(b"not a png") is None


def test_model_error_latches(monkeypatch, tmp_path):
    monkeypatch.setattr(table_model, "_ADAPTER", tmp_path / "missing")
    _reset_model()
    assert table_model.TableModel.available() is False
    # 闩锁: 二次调用仍 False, 不重复尝试
    assert table_model.TableModel.available() is False


def test_recognize_table_graceful_when_model_missing(monkeypatch, tmp_path):
    """权重缺失时 recognize_table(use_model=True) 不崩, 几何路径正常出结果."""
    import fitz

    from pdf2md import tables as tables_mod

    monkeypatch.setattr(table_model, "_ADAPTER", tmp_path / "missing")
    _reset_model()

    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    for ri, row in enumerate([["H1", "H2"], ["a1", "a2"], ["b1", "b2"]]):
        for ci, v in enumerate(row):
            page.insert_text(fitz.Point(50 + ci * 100, 50 + ri * 20), v, fontsize=10)
    frag = tables_mod.recognize_table(page, [0, 0, 400, 400], dpi=72, use_model=True)
    assert frag is not None
    assert frag["source"] == "geometry_native"
