# yunshu-OCR model asset notices

This file applies to the separately distributed `models-v1` Release archive.
The archive is an aggregate of independently licensed model files. The
yunshu-OCR repository license does not replace their licenses.

## DocLayout-YOLO DocStructBench 1280

- Asset: `models/runtime/layout/doclayout_yolo_docstructbench_imgsz1280_2501.pt`
- Project and author: DocLayout-YOLO, Zhiyuan Zhao and contributors / OpenDataLab
- Official model: https://huggingface.co/juliozhao/DocLayout-YOLO-DocStructBench-imgsz1280-2501
- Corresponding source: https://github.com/opendatalab/DocLayout-YOLO
- License: GNU Affero General Public License version 3 only (`AGPL-3.0-only`)
- SHA-256: `1b152460888dc30be6db7f5dfab28bde3dcc999e5202f46187a764a1699c80be`
- Changes: none; redistributed verbatim.

## pix2tex / LaTeX-OCR weights

- Assets: `models/runtime/pix2tex/weights.pth` and
  `models/runtime/pix2tex/image_resizer.pth`
- Project and author: LaTeX-OCR / pix2tex, Lukas Blecher
- Official weights release: https://github.com/lukas-blecher/LaTeX-OCR/releases/tag/v0.0.1
- Source code: https://github.com/lukas-blecher/LaTeX-OCR
- Weights license: Creative Commons Attribution-NonCommercial-ShareAlike 4.0
  International (`CC-BY-NC-SA-4.0`)
- SHA-256 (`weights.pth`):
  `a63d9141c53d266cb682fb5a8bd83bd5cbe283145e0e78ebdc0f895195a1dfaa`
- SHA-256 (`image_resizer.pth`):
  `1c3820659985ad142b526490bb25c23d977176ac2073591b3bddada692718458`
- Changes: none; redistributed verbatim.
- Restriction: these weights are licensed for non-commercial purposes. The
  MIT license of the pix2tex source code does not replace this weights license.

## PaddleOCR-derived ONNX weights

- Assets: PP-OCRv4 detection and recognition, PP-OCR mobile direction
  classification, and RapidTable SLANet Plus ONNX weights listed in
  `models/models.lock.json`
- Projects: PaddleOCR, RapidOCR, and RapidTable
- License: Apache License 2.0 (`Apache-2.0`)
- Changes: redistributed verbatim with filenames and hashes recorded in the
  checked-in manifest.

All assets are provided without warranty. See the license files bundled next
to this notice and `docs/research/model-release-redistribution-audit-2026-08-11.md`
in the source repository for the evidence and residual-risk assessment.
