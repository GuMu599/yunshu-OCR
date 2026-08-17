# Three-Agent PDF Reading Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Codex, Claude Code, and universal Yunshu-OCR skills with content-hash PDF↔Markdown binding and reliable page-level PDF fallback.

**Architecture:** Keep the conversion engine in the repository, strengthen `tools/pdf-reading/pdf2md.py` as the single JSON command boundary, and make all three skills call it through one portable launcher. Platform variants differ only in discovery and attachment-path guidance.

**Tech Stack:** Python 3.10+, PyMuPDF, pytest, Agent Skills `SKILL.md`.

---

### Task 1: Lock the helper contract with failing tests

**Files:**
- Create: `tests/test_pdf_reading_helper.py`
- Create: `tests/test_skill_packages.py`

- [ ] Test SHA-256 cache invalidation when a PDF changes without an mtime change.
- [ ] Test `locate` returns page, page label, bbox and element metadata.
- [ ] Test `render-page` produces a full-page image.
- [ ] Test all three Skill packages and README routing exist.
- [ ] Run the focused tests and confirm they fail because the new behavior is absent.

### Task 2: Implement durable binding and page commands

**Files:**
- Modify: `tools/pdf-reading/pdf2md.py`

- [ ] Add PDF and converter fingerprints plus `binding.json`.
- [ ] Require Markdown, layout, report and a valid binding before cache reuse.
- [ ] Run conversion with the highest-accuracy public CLI settings.
- [ ] Add `locate` and `render-page` JSON commands.
- [ ] Return file page number and page label from page-oriented commands.
- [ ] Run helper tests until green.

### Task 3: Package three platform Skills

**Files:**
- Create: `skills/shared/yunshu_pdf.py`
- Create: `skills/install.py`
- Create: `skills/codex/yunshu-ocr/SKILL.md`
- Create: `skills/claude/yunshu-ocr/SKILL.md`
- Create: `skills/universal/yunshu-ocr/SKILL.md`

- [ ] Implement a launcher that resolves `.yunshu-ocr-root` and delegates to the helper.
- [ ] Implement platform destination defaults and an explicit `--dest` override.
- [ ] Write concise platform-specific Skill triggers and the shared fallback contract.
- [ ] Run Skill package tests until green.

### Task 4: Make download choice obvious

**Files:**
- Modify: `README.md`
- Modify: `AI_README.md`
- Modify: `tools/pdf-reading/README.md`
- Modify: `docs/PDF与Markdown绑定读取技能设计.md`

- [ ] Put the Codex / Claude / universal choice near the top of README.
- [ ] Document installation commands and the need to start a new Agent task after installation.
- [ ] Replace the old “never render a full page” rule with bbox-first, full-page-second fallback.
- [ ] Document hash binding, `locate`, `render-page`, page labels and conflict handling.

### Task 5: Verify the complete result

**Files:**
- Test: `tests/test_pdf_reading_helper.py`
- Test: `tests/test_skill_packages.py`
- Test: existing repository test suites

- [ ] Run focused helper and Skill tests.
- [ ] Run syntax compilation for modified Python files.
- [ ] Run the existing test suite in proportion to available dependencies.
- [ ] Run `git diff --check` and inspect the final diff against the specification.
