# Formula Coverage Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover multi-line display equations and high-confidence inline equalities without turning captions, prose, dates, or ordinary numeric text into formulas.

**Architecture:** Keep DocLayout-YOLO as the visual candidate source, but consolidate nested formula boxes and split genuine stacked equation groups into line-level recognition units. Preserve the existing pix2tex path while adding a conservative native-text path for born-digital equations and inline equality formatting. Record observable counts so the four-document regression tests measure formula coverage rather than only process completion.

**Tech Stack:** Python 3.13, PyMuPDF, pix2tex, pytest, existing `pdf2md` pipeline and regression harness.

---

### Task 1: Lock Down The Two Missing-Formula Patterns

**Files:**
- Modify: `pdf2md/tests/test_formulas.py`
- Modify: `pdf2md/tests/test_layout_dedup.py`
- Modify: `pdf2md/tests/test_pipeline_contract.py`

- [x] **Step 1: Add a failing test for nested formula detector boxes**

Create a broad three-line formula box with two contained fragment boxes and assert that `suppress_overlapping_regions()` keeps one group container.

- [x] **Step 2: Add a failing test for stacked equation splitting**

Create a synthetic PDF with three displayed equalities in one detector region, run the real pipeline with deterministic recognition output, and assert that three formula items survive.

- [x] **Step 3: Add failing tests for inline equalities**

Assert that `2d sin theta = n lambda`, `R = 3r`, and `lambda = 0.154 nm` become inline LaTeX while dates and ordinary prose remain unchanged.

- [x] **Step 4: Run the focused tests and verify RED**

Run: `python -m pytest pdf2md/tests/test_formulas.py pdf2md/tests/test_layout_dedup.py pdf2md/tests/test_pipeline_contract.py -q`

Expected: the new assertions fail because nested formula consolidation, stacked-region processing, and inline conversion do not yet exist.

### Task 2: Recover Multi-Line Display Equations

**Files:**
- Modify: `pdf2md/layout.py`
- Modify: `pdf2md/formulas.py`
- Modify: `pdf2md/pipeline.py`

- [x] **Step 1: Consolidate nested formula detections**

Keep a broad formula container when it contains two or more same-class fragments, then rely on line splitting instead of processing overlapping boxes repeatedly.

- [x] **Step 2: Add vertical padding to split equation lines**

Extend each ink-line crop within the detector rectangle so summation limits, bars, superscripts, and subscripts are not clipped.

- [x] **Step 3: Recognize each stacked line independently**

Only split a tall region when its native text contains multiple equation signatures. Process every line through the existing formula recognizer, preserve an image when recognition is empty or structurally rejected, and keep caption rejection unchanged.

- [x] **Step 4: Run the focused tests and verify GREEN**

Run: `python -m pytest pdf2md/tests/test_formulas.py pdf2md/tests/test_layout_dedup.py pdf2md/tests/test_pipeline_contract.py -q`

Expected: all focused tests pass.

### Task 3: Preserve High-Confidence Inline Formulas

**Files:**
- Modify: `pdf2md/formulas.py`
- Modify: `pdf2md/pipeline.py`
- Modify: `pdf2md/tests/test_formulas.py`

- [x] **Step 1: Implement conservative inline equality extraction**

Convert only short Latin/Greek mathematical expressions containing `=`. Normalize Unicode operators, Greek symbols, decimal spacing, and obvious variable subscripts; do not match prose, dates, citations, or plain arithmetic without equality.

- [x] **Step 2: Apply conversion only to text-like Markdown items**

Run the formatter after content classification so headings and body text retain their structure while inline equalities are wrapped in `$...$`.

- [x] **Step 3: Count inline conversions in reports**

Add `inline_formulas` to `stats` and expose it through existing `layout.json` and `report.json` output.

- [x] **Step 4: Run formula and pipeline tests**

Run: `python -m pytest pdf2md/tests/test_formulas.py pdf2md/tests/test_pipeline_contract.py pdf2md/tests/test_cli.py -q`

Expected: all tests pass and caption/prose guards remain green.

### Task 4: Strengthen The Four-Document Regression Contract

**Files:**
- Modify: `pdf2md/regression.py`
- Modify: `pdf2md/tests/test_regression.py`
- Modify: `tests/benchmarks/documents/manifest.validation.jsonl`
- Create: `docs/research/formula-coverage-audit-2026-08-11.md`

- [x] **Step 1: Add observable formula minima**

Support `inline_formulas_min` and raise the SURADF display-formula minimum to cover the recovered stacked equations.

- [x] **Step 2: Record the four-document audit**

Document every real display and inline formula situation, the pre-fix behavior, root cause, and expected post-fix behavior.

- [x] **Step 3: Run regression unit tests**

Run: `python -m pytest pdf2md/tests/test_regression.py -q`

Expected: all regression-contract tests pass.

### Task 5: Verify The Real User Boundary

**Files:**
- No tracked source changes expected.
- Generate ignored outputs under `tmp/` and a new Desktop review directory.

- [x] **Step 1: Run the complete test suite**

Run: `python -m pytest tests pdf2md/tests`

Expected: zero failures.

- [x] **Step 2: Reconvert all four PDFs offline**

Run the normal CLI against the four supplied Desktop PDFs with `--offline` and fresh output directories.

- [x] **Step 3: Inspect formula counts and representative Markdown**

Require SURADF multi-line formulas to be present, graphene and physics inline equalities to use inline LaTeX, tennis to remain at zero display formulas, image references to resolve, and all reports to declare `offline=true`.

- [x] **Step 4: Run the four-document regression manifest**

Run: `python -m pdf2md.regression --manifest tests/benchmarks/documents/manifest.validation.jsonl --out tmp/formula-coverage-validation.json --offline`

Expected: all four cases pass.
