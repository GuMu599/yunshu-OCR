# README preview source

The preview uses the public arXiv version of *Attention Is All You Need*:

- Landing page: <https://arxiv.org/abs/1706.03762>
- PDF: <https://arxiv.org/pdf/1706.03762>
- Downloaded filename: `attention-is-all-you-need.pdf`
- SHA-256: `BDFAA68D8984F0DC02BEACA527B76F207D99B666D31D1DA728EE0728182DF697`

The PDF is not committed to this repository. It is downloaded into the ignored
`tmp/attention-is-all-you-need/` directory when rebuilding the preview. The
paper's first page includes the authors' reproduction notice; the README
preview keeps the attribution and is intended as a scholarly/tool demonstration.

Rebuild locally after downloading the PDF:

```powershell
$env:PYTHONIOENCODING = "utf-8"
python -m pdf2md.cli tmp/attention-is-all-you-need/attention-is-all-you-need.pdf `
  --output tmp/attention-is-all-you-need/ocr-utf8 --lang en --offline
python scripts/build_attention_preview.py
```
