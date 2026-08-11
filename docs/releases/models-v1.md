# models-v1

This Release provides the verified local model package required by yunshu-OCR.
Model installation may access GitHub, but PDF-to-Markdown conversion uses only
the installed local files: it does not call cloud APIs, download models, or
consume LLM tokens.

## Asset

- File: `pdf2md-models-v1.zip`
- Size: `185346805` bytes
- SHA-256: `daa85d380551a93f0464950181c3bc29ab16525a55b3a6664108183aa49c9fb0`

The archive contains seven inference weights plus the model attribution notice
and the applicable AGPL-3.0, CC-BY-NC-SA-4.0, and Apache-2.0 license texts.

## Important non-commercial restriction

The bundled pix2tex / LaTeX-OCR `weights.pth` and `image_resizer.pth` files are
licensed under `CC-BY-NC-SA-4.0` and are provided for non-commercial use only.
The MIT license of the pix2tex source code does not replace the weights license.
Do not use this model package for a commercial product or service without
obtaining separate permission or replacing those weights with commercially
permitted assets.

DocLayout-YOLO is distributed under `AGPL-3.0-only`. The RapidOCR and
RapidTable ONNX assets are distributed under `Apache-2.0`. Full attribution,
source links, hashes, and residual-risk notes are included in the archive and
documented in the repository.

## Install and verify

```powershell
python -m pdf2md.models install
python -m pdf2md.models verify
```

After verification succeeds, normal conversion remains strictly offline.
