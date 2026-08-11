# yunshu-OCR v1.0.0 source Release

This is the final source archive for the offline PDF-to-Markdown toolchain.
Install runtime dependencies from `requirements-lock.txt`, then install and
verify the model asset Release with `python -m pdf2md.models install` and
`python -m pdf2md.models verify`.

The source archive intentionally excludes maintainer-only material: automated
tests, benchmark and regression runners, benchmark PDFs, local conversion
outputs, caches, and development dependency files. The Git repository keeps
the test suite and regression corpus for future maintenance; they are not part
of this user-facing archive.

The companion model asset is `pdf2md-models-v1.zip`. It contains the seven
verified inference weights and the applicable license texts. Its SHA-256 is
recorded in `models/models.lock.json` and `docs/releases/models-v1.md`.

## Verification

The release builder rejects forbidden archive entries after `git archive` and
prints the archive size and SHA-256. The final delivery directory also contains
`SHA256SUMS.txt` covering both the source and model archives.
