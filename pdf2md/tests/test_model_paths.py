"""Inference adapters resolve only verified Release model paths."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md import formulas, layout, models as model_assets, ocr  # noqa: E402


def test_default_layout_and_formula_paths_come_from_manifest(monkeypatch):
    monkeypatch.delenv("PDF2MD_LAYOUT_MODEL", raising=False)

    assert layout.resolve_model_path() == model_assets.model_path("layout")
    assert formulas.FormulaModel.checkpoint_dir() == model_assets.model_path(
        "pix2tex_weights"
    ).parent


def test_rapidocr_final_output_does_not_construct_visualizer(monkeypatch):
    sys.path.insert(0, str(ocr._ADAPTER))
    import rapidocr.main as rapid_main

    monkeypatch.setattr(
        rapid_main,
        "VisRes",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("visualizer constructed")),
        raising=False,
    )
    monkeypatch.setattr(rapid_main, "map_boxes_to_original", lambda boxes, *args: boxes)
    engine = rapid_main.RapidOCR.__new__(rapid_main.RapidOCR)
    engine.return_word_box = False
    engine.filter_by_text_score = lambda output: output
    engine.cfg = SimpleNamespace(
        Global=SimpleNamespace(text_score=0.5, font_path=None),
        Rec=SimpleNamespace(lang_type="ch"),
    )
    det = rapid_main.TextDetOutput(
        boxes=np.array([[[0, 0], [2, 0], [2, 2], [0, 2]]]),
        scores=[0.9],
        elapse=0.1,
    )
    cls = rapid_main.TextClsOutput(elapse=0.0)
    rec = rapid_main.TextRecOutput(
        imgs=[np.zeros((2, 2, 3), dtype=np.uint8)],
        txts=("text",),
        scores=(0.9,),
        word_results=(None,),
        elapse=0.1,
    )

    output = engine.build_final_output(
        np.zeros((4, 4, 3), dtype=np.uint8), det, cls, rec, [], {}
    )

    assert output.viser is None


def test_rapidocr_text_recognition_does_not_construct_visualizer(monkeypatch):
    sys.path.insert(0, str(ocr._ADAPTER))
    import rapidocr.ch_ppocr_rec.main as rec_main

    monkeypatch.setattr(
        rec_main,
        "VisRes",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("visualizer constructed")),
        raising=False,
    )
    recognizer = rec_main.TextRecognizer.__new__(rec_main.TextRecognizer)
    recognizer.rec_batch_num = 1
    recognizer.rec_image_shape = (3, 48, 320)
    recognizer.session = lambda batch: np.zeros((1, 1), dtype=np.float32)
    recognizer.postprocess_op = lambda *args, **kwargs: ([('text', 0.9)], [None])
    recognizer.resize_norm_img = lambda image, ratio: np.zeros(
        (3, 48, 320), dtype=np.float32
    )
    recognizer.cfg = SimpleNamespace(lang_type="ch", font_path=None)

    output = recognizer(
        rec_main.TextRecInput(
            img=np.zeros((8, 16, 3), dtype=np.uint8),
            return_word_box=False,
        )
    )

    assert output.viser is None


def test_formula_arguments_use_absolute_release_checkpoint():
    arguments = formulas.FormulaModel.arguments()

    assert Path(arguments["checkpoint"]).is_absolute()
    assert Path(arguments["checkpoint"]) == model_assets.model_path("pix2tex_weights")
    assert Path(arguments["config"]).is_absolute()
