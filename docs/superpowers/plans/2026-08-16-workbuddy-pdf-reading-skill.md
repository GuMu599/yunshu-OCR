# WorkBuddy PDF Reading Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an upload-ready WorkBuddy variant that preserves Yunshu-OCR's PDF-to-Markdown binding and page-level PDF verification behavior.

**Architecture:** Keep OCR and PDF-reading logic in the existing repository. Add a WorkBuddy-specific skill source plus a packager that creates a repository-bound ZIP containing the shared launcher and root marker. Extend documentation and tests without changing the three existing directory-install variants.

**Tech Stack:** Python 3, `zipfile`, YAML metadata, pytest, Markdown.

---

### Task 1: Specify the missing WorkBuddy package behavior

**Files:**
- Modify: `tests/test_skill_packages.py`

- [ ] **Step 1: Write failing tests**

Add `workbuddy` to the source variant contract and add focused tests for:

```python
import zipfile


def test_workbuddy_manifest_has_minimum_enterprise_metadata():
    text = (ROOT / "skills/workbuddy/yunshu-ocr/manifest.yaml").read_text(encoding="utf-8")
    assert "name: yunshu-ocr" in text
    assert "version: 1.0.0" in text
    assert "category: document-processing" in text
    assert "author: GuMu599" in text


def test_workbuddy_packager_creates_uploadable_repository_bound_zip(tmp_path):
    installer = _load_installer()
    artifact = installer.package_workbuddy(tmp_path / "yunshu-ocr-workbuddy.zip")
    with zipfile.ZipFile(artifact) as archive:
        assert set(archive.namelist()) == {
            "yunshu-ocr/SKILL.md",
            "yunshu-ocr/manifest.yaml",
            "yunshu-ocr/.yunshu-ocr-root",
            "yunshu-ocr/scripts/yunshu_pdf.py",
        }
        assert Path(archive.read("yunshu-ocr/.yunshu-ocr-root").decode()).resolve() == ROOT.resolve()


def test_workbuddy_packager_refuses_to_overwrite_without_force(tmp_path):
    installer = _load_installer()
    artifact = tmp_path / "yunshu-ocr-workbuddy.zip"
    installer.package_workbuddy(artifact)
    with pytest.raises(FileExistsError):
        installer.package_workbuddy(artifact)
    assert installer.package_workbuddy(artifact, force=True) == artifact.resolve()


def test_readmes_route_workbuddy_users_to_the_upload_package():
    for filename in ("README.md", "AI_README.md"):
        text = (ROOT / filename).read_text(encoding="utf-8")
        assert "WorkBuddy" in text
        assert "python skills/install.py workbuddy" in text
        assert "yunshu-ocr-workbuddy.zip" in text
```

The ZIP test must assert this exact logical layout:

```text
yunshu-ocr/SKILL.md
yunshu-ocr/manifest.yaml
yunshu-ocr/.yunshu-ocr-root
yunshu-ocr/scripts/yunshu_pdf.py
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
python -m pytest tests/test_skill_packages.py -q
```

Expected: failures because the WorkBuddy source, manifest, packaging function, and README routing do not exist.

### Task 2: Add WorkBuddy skill source and packaging

**Files:**
- Create: `skills/workbuddy/yunshu-ocr/SKILL.md`
- Create: `skills/workbuddy/yunshu-ocr/manifest.yaml`
- Create: `skills/workbuddy/yunshu-ocr/scripts/yunshu_pdf.py`
- Modify: `skills/install.py`

- [ ] **Step 1: Write the WorkBuddy skill**

Use the same core contract as the other variants, with WorkBuddy-specific instructions for authorized attachment paths, script confirmation, local-only processing, and the escalation chain:

```text
ensure -> Markdown -> locate -> render -> render-page -> adjacent page
```

The description must start with `Use when` and include WorkBuddy PDF attachment/path triggers.

- [ ] **Step 2: Add minimum enterprise metadata**

Create:

```yaml
name: yunshu-ocr
version: 1.0.0
description: Offline high-accuracy PDF reading with Markdown binding and page verification
category: document-processing
author: GuMu599
```

- [ ] **Step 3: Implement packaging**

Add:

```python
def package_workbuddy(destination: str | Path | None = None, *, force: bool = False) -> Path:
    source = SKILLS / "workbuddy" / "yunshu-ocr"
    target = (
        Path(destination).expanduser().resolve()
        if destination
        else (ROOT / "dist" / "yunshu-ocr-workbuddy.zip").resolve()
    )
    if target.exists() and not force:
        raise FileExistsError(
            f"destination already exists: {target}; choose another --dest or pass --force"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(source / "SKILL.md", "yunshu-ocr/SKILL.md")
        archive.write(source / "manifest.yaml", "yunshu-ocr/manifest.yaml")
        archive.write(SKILLS / "shared" / "yunshu_pdf.py", "yunshu-ocr/scripts/yunshu_pdf.py")
        archive.writestr("yunshu-ocr/.yunshu-ocr-root", str(ROOT.resolve()))
    return target
```

Use `zipfile.ZipFile(..., ZIP_DEFLATED)` and write the repository root marker directly into the archive. Default to `dist/yunshu-ocr-workbuddy.zip`. Reject existing output unless `force=True`. Keep `install_skill()` behavior unchanged for Codex, Claude, and universal variants.

- [ ] **Step 4: Route the CLI**

`python skills/install.py workbuddy [--dest output.zip] [--force]` must call `package_workbuddy()` and return JSON containing `artifact`, `repository`, and the WorkBuddy upload hint.

- [ ] **Step 5: Verify GREEN**

Run:

```powershell
python -m pytest tests/test_skill_packages.py -q
```

Expected: all package tests pass.

### Task 3: Document four host variants

**Files:**
- Modify: `README.md`
- Modify: `AI_README.md`

- [ ] **Step 1: Update the human README**

Change three-version wording to four-version wording, add WorkBuddy to the selection table, and document:

```powershell
python skills/install.py workbuddy
```

Explain how to upload `dist/yunshu-ocr-workbuddy.zip`, that the repository must remain at the packaged location, and that no accuracy initialization is required.

- [ ] **Step 2: Update the AI-facing README**

Add a dedicated WorkBuddy section covering selection, package generation, authorized local PDF paths, script confirmation, and the shared PDF fallback chain. Update selection rules so WorkBuddy does not choose the universal variant.

- [ ] **Step 3: Re-run focused tests**

Run:

```powershell
python -m pytest tests/test_skill_packages.py -q
```

Expected: all tests pass.

### Task 4: Verify the complete vertical slice

**Files:**
- Verify: `skills/install.py`
- Verify: `skills/workbuddy/yunshu-ocr/`
- Verify: `README.md`
- Verify: `AI_README.md`

- [ ] **Step 1: Generate the real artifact**

Run:

```powershell
python skills/install.py workbuddy --force
```

Expected: JSON reports `dist/yunshu-ocr-workbuddy.zip` and WorkBuddy upload instructions.

- [ ] **Step 2: Inspect the ZIP**

Verify the four required entries, parse `manifest.yaml`, and confirm `.yunshu-ocr-root` resolves to the current repository.

- [ ] **Step 3: Run regression tests**

Run:

```powershell
python -m pytest tests/test_skill_packages.py tests/test_pdf_reading_helper.py -q
python -m compileall -q skills tools/pdf-reading
git diff --check
```

Expected: tests and compilation pass; diff check is clean.

- [ ] **Step 4: Report evidence**

Report source paths, ZIP path, tests run, any pre-existing unrelated failures, and the exact WorkBuddy upload flow. Do not claim automatic routing was verified unless it was exercised in a real WorkBuddy client.
