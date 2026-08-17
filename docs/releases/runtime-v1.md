# runtime-v1

This Release is the fixed, lightweight runtime used by portable Yunshu-OCR Agent
Skills. It contains the current PDF-to-Markdown engine, PDF/Markdown binding and page
verification helper, local OCR/table adapters, dependency manifests, and license
notices. It does not contain model weights, tests, Skill launchers, caches, PDFs, or
generated output.

## Asset

- File: `yunshu-ocr-runtime-v1.zip`
- Size: `349674` bytes
- SHA-256: `f4f95dbc12ffd060ce662ca1dbc59f2d5b867ccd703183f5f829502e96f84030`
- Release: `https://github.com/GuMu599/yunshu-OCR/releases/tag/runtime-v1`

The archive was published because the older `v1.0.0` source Release predates
`tools/pdf-reading/pdf2md.py` and therefore cannot provide the current `locate`,
`render-page`, and binding validation contract.

## Reproducible contents

The archive was built from commit `7c82d6d` using Git's tracked-file archive and the
repository's `export-ignore` rules:

```powershell
git archive --format=zip `
  --prefix=yunshu-OCR-runtime-v1/ `
  --output=dist/yunshu-ocr-runtime-v1.zip `
  7c82d6d -- `
  pdf2md tools/pdf-reading models/production models/models.lock.json `
  requirements.txt requirements-lock.txt LICENSE NOTICE THIRD_PARTY_LICENSES
```

`models-v1` remains a separate Release. The portable launcher verifies this runtime
archive before extraction, then delegates model archive and per-file verification to
`pdf2md.models`.
