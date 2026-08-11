"""Executable model formats are loaded only after integrity verification."""

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md import formulas, layout  # noqa: E402


def test_custom_layout_model_requires_an_explicit_matching_digest(tmp_path):
    model = tmp_path / "custom.pt"
    model.write_bytes(b"trusted test weights")

    with pytest.raises(RuntimeError, match="model_untrusted:layout"):
        layout.preflight_layout_model(model)

    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    status = layout.preflight_layout_model(model, expected_sha256=digest)
    assert status["sha256"] == digest
    assert status["verified"] is True


def test_layout_model_digest_mismatch_is_rejected(tmp_path):
    model = tmp_path / "custom.pt"
    model.write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="model_integrity:layout"):
        layout.preflight_layout_model(model, expected_sha256="0" * 64)


def test_pix2tex_checkpoint_mismatch_disables_executable_loader(tmp_path):
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir()
    (checkpoint_dir / "weights.pth").write_bytes(b"untrusted pickle")
    (checkpoint_dir / "image_resizer.pth").write_bytes(b"untrusted pickle")

    status = formulas.FormulaModel.checkpoint_status(checkpoint_dir)
    assert status["available"] is False
    assert status["error"] == "model_integrity:pix2tex"
