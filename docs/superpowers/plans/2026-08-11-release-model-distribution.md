# Release Model Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make model installation an explicit GitHub Release operation while guaranteeing that PDF conversion uses only verified local models and never downloads during conversion.

**Architecture:** A single `pdf2md.models` module owns the versioned manifest, model paths, verification, secure installation, and deterministic release building. Existing layout, OCR, table, and formula adapters resolve their default weights through that module; the conversion pipeline performs strict preflight before creating output.

**Tech Stack:** Python 3.13, standard-library JSON/urllib/zipfile/hashlib/tempfile, PyMuPDF, pytest, Ruff, GitHub Releases.

---

### Task 1: Versioned Model Manifest And Local Verification

**Files:**
- Create: `models/models.lock.json`
- Create: `pdf2md/models.py`
- Create: `pdf2md/tests/test_models.py`

- [ ] **Step 1: Write failing manifest and verification tests**

```python
def test_manifest_uses_fixed_release_and_unique_paths():
    manifest = model_assets.load_manifest()
    assert manifest.release.tag == "models-v1"
    assert "latest" not in manifest.release.url
    assert len({item.name for item in manifest.models}) == 7
    assert len({item.install_path for item in manifest.models}) == 7


def test_verify_models_reports_missing_and_install_command(tmp_path):
    manifest = write_test_manifest(tmp_path, model_bytes={"layout": b"layout"})
    result = model_assets.verify_models(manifest)
    assert result["available"] is False
    assert "python -m pdf2md.models install" in result["error"]
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m pytest pdf2md/tests/test_models.py -q`

Expected: collection fails because `pdf2md.models` does not exist.

- [ ] **Step 3: Implement the manifest module and checked paths**

```python
@dataclass(frozen=True)
class ModelFile:
    name: str
    install_path: str
    size: int
    sha256: str


def model_path(name: str, manifest: ModelManifest | None = None) -> Path:
    selected = manifest or load_manifest()
    item = selected.by_name(name)
    return selected.repo_root / Path(item.install_path)
```

Validate schema version, fixed tag URL, relative normalized paths, unique names and paths, positive sizes, and lowercase 64-character SHA-256 values. `verify_models()` must distinguish missing, wrong-size, wrong-hash, and Git LFS pointer states.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `python -m pytest pdf2md/tests/test_models.py -q`

Expected: all manifest and local verification tests pass.

- [ ] **Step 5: Commit the vertical slice**

```powershell
git add models/models.lock.json pdf2md/models.py pdf2md/tests/test_models.py
git commit -m "feat: add versioned model manifest"
```

### Task 2: Secure Release Installation And Deterministic Building

**Files:**
- Modify: `pdf2md/models.py`
- Modify: `pdf2md/tests/test_models.py`
- Create: `scripts/build_model_release.ps1`

- [ ] **Step 1: Write failing archive-security and atomic-install tests**

```python
@pytest.mark.parametrize("member", ["../escape.pt", "/absolute.pt", "C:/drive.pt", "dir\\escape.pt"])
def test_install_rejects_unsafe_archive_members(tmp_path, member):
    manifest, archive = make_release(tmp_path, extra_member=member)
    with pytest.raises(ModelInstallError, match="unsafe_archive"):
        model_assets.install_models(manifest, source_url=archive.as_uri())


def test_failed_install_preserves_verified_existing_models(tmp_path):
    manifest, archive = make_release(tmp_path, corrupt_model="layout")
    existing = install_existing_verified_files(manifest)
    with pytest.raises(ModelInstallError):
        model_assets.install_models(manifest, source_url=archive.as_uri())
    assert existing.read_bytes() == b"previous-verified-layout"
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m pytest pdf2md/tests/test_models.py -q`

Expected: failures because installation and archive building are not implemented.

- [ ] **Step 3: Implement bounded download, safe extraction, verification, rollback, and deterministic ZIP**

```python
def install_models(manifest=None, *, source_url=None):
    selected = manifest or load_manifest()
    with TemporaryDirectory(dir=selected.repo_root) as temp_dir:
        archive = _download_release(selected, Path(temp_dir), source_url)
        _verify_archive(archive, selected.release)
        staged = _extract_declared_members(archive, selected, Path(temp_dir) / "stage")
        _verify_staged_models(staged, selected)
        _publish_with_rollback(staged, selected)
    return verify_models(selected)
```

Reject symlinks, duplicate names, undeclared files, path traversal, wrong archive size/hash, oversized download, and oversized expansion. Build ZIP entries in sorted order with timestamp `1980-01-01 00:00:00`, regular-file mode `0644`, and fixed compression settings.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `python -m pytest pdf2md/tests/test_models.py -q`

Expected: all installer and deterministic-build tests pass.

- [ ] **Step 5: Commit the vertical slice**

```powershell
git add pdf2md/models.py pdf2md/tests/test_models.py scripts/build_model_release.ps1
git commit -m "feat: install verified release models"
```

### Task 3: Route Every Inference Adapter Through The Manifest

**Files:**
- Modify: `pdf2md/layout.py`
- Modify: `pdf2md/formulas.py`
- Modify: `pdf2md/ocr.py`
- Modify: `pdf2md/table_model.py`
- Modify: `models/production/rapidocr-adapter/rapidocr/main.py`
- Modify: `models/production/rapidocr-adapter/rapidocr/ch_ppocr_rec/main.py`
- Modify: `pdf2md/tests/test_preflight.py`
- Modify: `pdf2md/tests/test_model_security.py`
- Create: `pdf2md/tests/test_model_paths.py`

- [ ] **Step 1: Write failing repository-path and no-font-download tests**

```python
def test_default_layout_and_formula_paths_come_from_manifest(monkeypatch):
    assert layout.resolve_model_path() == model_assets.model_path("layout")
    assert formulas.FormulaModel.checkpoint_dir() == model_assets.model_path("pix2tex_weights").parent


def test_rapidocr_inference_does_not_construct_visualizer(monkeypatch):
    monkeypatch.setattr(rec_module, "VisRes", lambda **kwargs: (_ for _ in ()).throw(AssertionError("network-capable visualizer")))
    output = call_text_recognizer_with_fake_engine()
    assert output.viser is None
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m pytest pdf2md/tests/test_model_paths.py pdf2md/tests/test_preflight.py pdf2md/tests/test_model_security.py -q`

Expected: default layout and formula paths still point to user caches, and RapidOCR constructs `VisRes`.

- [ ] **Step 3: Implement manifest-backed adapters**

```python
def resolve_model_path(explicit=None):
    selected = explicit or os.environ.get("PDF2MD_LAYOUT_MODEL")
    return Path(selected).expanduser().resolve() if selected else model_assets.model_path("layout")


def _pix2tex_arguments(checkpoint_dir):
    package = _pix2tex_package_path()
    return Munch({
        "config": str(package / "model" / "settings" / "config.yaml"),
        "checkpoint": str(checkpoint_dir / "weights.pth"),
        "no_cuda": True,
        "no_resize": False,
    })
```

Read OCR and table hashes from the manifest. Return inference outputs with `viser=None`; visualization is outside this project's conversion contract and may not download fonts during conversion.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `python -m pytest pdf2md/tests/test_model_paths.py pdf2md/tests/test_preflight.py pdf2md/tests/test_model_security.py -q`

Expected: all adapter path, integrity, and no-font-download tests pass.

- [ ] **Step 5: Commit the vertical slice**

```powershell
git add pdf2md/layout.py pdf2md/formulas.py pdf2md/ocr.py pdf2md/table_model.py models/production/rapidocr-adapter/rapidocr/main.py models/production/rapidocr-adapter/rapidocr/ch_ppocr_rec/main.py pdf2md/tests/test_model_paths.py pdf2md/tests/test_preflight.py pdf2md/tests/test_model_security.py
git commit -m "fix: make conversion use release models"
```

### Task 4: Enforce Offline Conversion And Strict Preflight

**Files:**
- Modify: `pdf2md/pipeline.py`
- Modify: `pdf2md/cli.py`
- Modify: `pdf2md/tests/test_cli.py`
- Modify: `pdf2md/tests/test_preflight_components.py`
- Create: `pdf2md/tests/test_conversion_offline.py`

- [ ] **Step 1: Write failing strict-preflight and socket-denial tests**

```python
def test_default_preflight_requires_formula_ocr_and_table(monkeypatch):
    monkeypatch.setattr(formulas.FormulaModel, "checkpoint_status", lambda: {"available": False, "error": "missing"})
    with pytest.raises(RuntimeError, match="model_missing.*install"):
        pipeline.preflight(strict=True)


def test_cli_conversion_is_always_offline(monkeypatch, tmp_path):
    captured = run_cli_with_fake_converter(monkeypatch, tmp_path)
    assert captured["offline"] is True
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m pytest pdf2md/tests/test_cli.py pdf2md/tests/test_preflight_components.py pdf2md/tests/test_conversion_offline.py -q`

Expected: preflight only warns for optional model failures and CLI defaults to online.

- [ ] **Step 3: Implement strict default behavior**

```python
def preflight(..., formula_engine="auto", strict=False):
    result["formula"] = FormulaModel.checkpoint_status() if formula_engine != "rapidocr" else {"disabled": True}
    failures = [name for name, state in result.items() if isinstance(state, dict) and not state.get("available") and not state.get("disabled")]
    if strict and failures:
        raise RuntimeError(f"model_missing:{','.join(failures)}; run: python -m pdf2md.models install")
    return result
```

The production pipeline calls `preflight(strict=True)` before output creation. Explicit `--no-ocr`, `--no-table-model`, and `--formula-engine rapidocr` mark their corresponding models disabled. CLI conversion always passes `offline=True`.

- [ ] **Step 4: Run focused tests and confirm GREEN**

Run: `python -m pytest pdf2md/tests/test_cli.py pdf2md/tests/test_preflight_components.py pdf2md/tests/test_conversion_offline.py -q`

Expected: all strict preflight and offline conversion tests pass.

- [ ] **Step 5: Commit the vertical slice**

```powershell
git add pdf2md/pipeline.py pdf2md/cli.py pdf2md/tests/test_cli.py pdf2md/tests/test_preflight_components.py pdf2md/tests/test_conversion_offline.py
git commit -m "fix: keep PDF conversion strictly offline"
```

### Task 5: Build The Real Asset, Lock Dependencies, Document, And Verify

**Files:**
- Modify: `models/models.lock.json`
- Create: `requirements-lock.txt`
- Modify: `.gitignore`
- Modify: `README.md`
- Modify: `pdf2md/README.md`
- Modify: `docs/VENDORED.md`
- Modify: `NOTICE`

- [ ] **Step 1: Build the deterministic local Release asset**

Run: `python -m pdf2md.models build-release --output tmp/pdf2md-models-v1.zip`

Expected: seven verified weights, deterministic ZIP path, byte count, and archive SHA-256 are printed. Patch those exact archive values into `models/models.lock.json`, rebuild, and verify the SHA-256 is unchanged.

- [ ] **Step 2: Exercise the installer against the local asset**

Run: `python -m pdf2md.models verify`

Expected: all seven repository model paths report verified after installing the local archive into a temporary clone-shaped directory in the focused integration test.

- [ ] **Step 3: Generate and document the dependency lock**

Generate exact Windows Python 3.13 dependency versions from the installed project dependency closure and write `requirements-lock.txt`. Do not include unrelated global packages such as `texify`.

- [ ] **Step 4: Update documentation and distribution exclusions**

Document the three-command flow (`clone`, model install, convert), fixed Release tag, offline conversion semantics, model verification failures, local asset upload procedure, and licensing gate. Keep `tmp/`, archives, weights, PDFs, caches, and `FZYTK.TTF` ignored.

- [ ] **Step 5: Run complete verification**

```powershell
python -m pytest -q
python -m compileall -q pdf2md models/production/rapidocr-adapter/rapidocr models/production/table-adapter/rapid_table
$changedPython = @(git diff --name-only f7e8ad1..HEAD -- '*.py')
python -m ruff check $changedPython
git diff --check
python -m pdf2md.models status
python -m pdf2md.models verify
```

Expected: the full suite passes; compilation, changed-file Ruff, whitespace checks, and seven-model verification pass. Then run the four-document regression with sockets denied during conversion and confirm all four cases pass.

- [ ] **Step 6: Commit the completed Release workflow locally**

```powershell
git add .gitignore README.md NOTICE docs/VENDORED.md pdf2md/README.md models/models.lock.json requirements-lock.txt
git commit -m "docs: document release model installation"
```

Do not push, create a remote Release, or add `tmp/pdf2md-models-v1.zip` to Git.
