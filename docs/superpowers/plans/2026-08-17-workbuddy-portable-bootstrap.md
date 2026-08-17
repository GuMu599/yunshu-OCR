# WorkBuddy Portable Runtime Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the WorkBuddy Skill ZIP portable across machines by removing its absolute repository marker and automatically installing a verified, versioned Yunshu-OCR runtime on first use for later offline PDF processing.

**Architecture:** Keep `skills/shared/yunshu_pdf.py` as the single launcher source copied into all host variants. The launcher first resolves explicit or legacy local repositories, then falls back to a versioned OS cache where it securely downloads the fixed v1.0.0 source archive, creates a virtual environment, installs dependencies and verified models, records completion state, and dispatches the original PDF command with the managed Python. `skills/install.py` only assembles the small WorkBuddy ZIP and never performs runtime setup.

**Tech Stack:** Python 3.10+, standard library (`hashlib`, `json`, `os`, `platform`, `shutil`, `subprocess`, `tempfile`, `time`, `urllib.request`, `venv`, `zipfile`), pytest, GitHub Releases.

---

## File Map

- Create `tests/test_skill_runtime_bootstrap.py`: isolated tests for platform cache policy, repository resolution, download verification, safe extraction, dependency selection, staged installation, offline reuse, and JSON errors.
- Modify `tests/test_skill_packages.py`: WorkBuddy ZIP portability contract and documentation assertions.
- Modify `skills/shared/yunshu_pdf.py`: portable discovery, managed bootstrap, state validation, error reporting, and helper dispatch.
- Copy `skills/shared/yunshu_pdf.py` to the four committed variant launchers so directly downloaded source directories remain self-contained.
- Modify `skills/install.py`: remove the WorkBuddy absolute-path marker and repository-bound output.
- Modify `skills/workbuddy/yunshu-ocr/SKILL.md`: first-use download, cache, offline reuse, recovery guidance, and Token boundary.
- Modify `models/models.lock.json`: replace obsolete release repository/URL with `GuMu599/yunshu-OCR`.
- Modify `README.md` and `AI_README.md`: portable WorkBuddy setup, prerequisites, first-use size/time expectations, and cross-platform verification limits.
- Regenerate `dist/yunshu-ocr-workbuddy.zip`: final uploadable artifact. `dist/` is ignored, so verify it locally and report its path without adding it to Git.

### Task 1: Lock the portable package contract

**Files:**
- Modify: `tests/test_skill_packages.py`
- Test: `tests/test_skill_packages.py`

- [ ] **Step 1: Replace the repository-bound ZIP test with failing portability assertions**

Replace `test_workbuddy_packager_creates_uploadable_repository_bound_zip` with:

```python
def test_workbuddy_packager_creates_portable_upload_zip(tmp_path):
    installer = _load_installer()
    artifact = installer.package_workbuddy(tmp_path / "yunshu-ocr-workbuddy.zip")

    assert artifact == (tmp_path / "yunshu-ocr-workbuddy.zip").resolve()
    with zipfile.ZipFile(artifact) as archive:
        assert set(archive.namelist()) == {
            "SKILL.md",
            "manifest.yaml",
            "scripts/yunshu_pdf.py",
        }
        assert all(not Path(name).name.startswith(".") for name in archive.namelist())
        text = "\n".join(
            archive.read(name).decode("utf-8")
            for name in archive.namelist()
            if name.endswith((".md", ".yaml", ".py", ".txt", ".json"))
        )
        assert "yunshu-ocr-root" not in text
        assert str(ROOT.resolve()) not in text
        assert "E:\\Codex" not in text
        assert "C:\\Users\\GuMu" not in text
```

Extend `test_readmes_route_workbuddy_users_to_the_upload_package`:

```python
def test_readmes_describe_portable_first_use_and_offline_reuse():
    for filename in ("README.md", "AI_README.md"):
        text = (ROOT / filename).read_text(encoding="utf-8")
        assert "首次使用" in text
        assert "185 MB" in text
        assert "离线" in text
        assert "YUNSHU_OCR_ROOT" in text
        assert "仓库绝对路径" not in text
        assert "重新上传" not in text
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_skill_packages.py -q
```

Expected: the ZIP test fails because `references/yunshu-ocr-root.txt` is still present; the README test fails because current documentation still describes a repository-bound package.

- [ ] **Step 3: Make only the ZIP assembly portable**

Change `package_workbuddy()` in `skills/install.py` to write exactly three entries:

```python
def package_workbuddy(
    destination: str | Path | None = None,
    *,
    force: bool = False,
) -> Path:
    source = SKILLS / WORKBUDDY_VARIANT / "yunshu-ocr"
    target = (
        Path(destination).expanduser().resolve()
        if destination
        else WORKBUDDY_DEFAULT_ARTIFACT.resolve()
    )
    if target.exists() and not force:
        raise FileExistsError(
            f"destination already exists: {target}; choose another --dest or pass --force"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(source / "SKILL.md", "SKILL.md")
        archive.write(source / "manifest.yaml", "manifest.yaml")
        archive.write(SKILLS / "shared" / "yunshu_pdf.py", "scripts/yunshu_pdf.py")
    return target
```

Remove `"repository": str(ROOT.resolve())` from the WorkBuddy success JSON. Keep the existing upload hint.

- [ ] **Step 4: Run the exact ZIP test**

Run:

```powershell
python -m pytest tests/test_skill_packages.py::test_workbuddy_packager_creates_portable_upload_zip -q
```

Expected: PASS.

- [ ] **Step 5: Commit the package boundary**

```powershell
git add -- tests/test_skill_packages.py skills/install.py
git commit -m "fix: remove WorkBuddy repository path binding"
```

### Task 2: Define cache and repository resolution policy

**Files:**
- Create: `tests/test_skill_runtime_bootstrap.py`
- Modify: `skills/shared/yunshu_pdf.py`
- Test: `tests/test_skill_runtime_bootstrap.py`

- [ ] **Step 1: Add failing path-policy and resolution tests**

Create `tests/test_skill_runtime_bootstrap.py` with loader helpers and these tests:

```python
import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "skills" / "shared" / "yunshu_pdf.py"


def _load_launcher():
    spec = importlib.util.spec_from_file_location("yunshu_skill_launcher", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _make_repo(path: Path) -> Path:
    helper = path / "tools" / "pdf-reading" / "pdf2md.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("print('helper')\n", encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("system", "env", "home", "expected"),
    [
        ("Windows", {"LOCALAPPDATA": "C:/Cache"}, "C:/Users/Test", Path("C:/Cache/yunshu-ocr")),
        ("Darwin", {}, "/Users/test", Path("/Users/test/Library/Caches/yunshu-ocr")),
        ("Linux", {"XDG_CACHE_HOME": "/var/tmp/cache"}, "/home/test", Path("/var/tmp/cache/yunshu-ocr")),
        ("Linux", {}, "/home/test", Path("/home/test/.cache/yunshu-ocr")),
    ],
)
def test_cache_root_follows_platform_policy(system, env, home, expected):
    launcher = _load_launcher()
    assert launcher._cache_root(system=system, env=env, home=Path(home)) == expected


def test_explicit_valid_override_wins(monkeypatch, tmp_path):
    launcher = _load_launcher()
    repo = _make_repo(tmp_path / "override")
    monkeypatch.setenv("YUNSHU_OCR_ROOT", str(repo))
    assert launcher._find_existing_repo() == repo.resolve()


def test_explicit_invalid_override_is_not_silently_ignored(monkeypatch, tmp_path):
    launcher = _load_launcher()
    monkeypatch.setenv("YUNSHU_OCR_ROOT", str(tmp_path / "missing"))
    with pytest.raises(launcher.BootstrapError) as raised:
        launcher._find_existing_repo()
    assert raised.value.code == "override_invalid"


def test_legacy_marker_remains_supported(monkeypatch, tmp_path):
    launcher = _load_launcher()
    repo = _make_repo(tmp_path / "repo")
    skill = tmp_path / "skill"
    (skill / "scripts").mkdir(parents=True)
    (skill / ".yunshu-ocr-root").write_text(str(repo), encoding="utf-8")
    monkeypatch.delenv("YUNSHU_OCR_ROOT", raising=False)
    monkeypatch.setattr(launcher, "_script_path", lambda: skill / "scripts" / "yunshu_pdf.py")
    assert launcher._find_existing_repo() == repo.resolve()


def test_release_constants_match_published_assets():
    launcher = _load_launcher()
    assert launcher.SOURCE_URL == "https://github.com/GuMu599/yunshu-OCR/releases/download/v1.0.0/yunshu-OCR-v1.0.0-source.zip"
    assert launcher.SOURCE_SIZE == 412019
    assert launcher.SOURCE_SHA256 == "4f47c511fe771e80ddecebaf075a00d236ae5daff356290095533402850873a7"
    assert launcher.MODEL_URL == "https://github.com/GuMu599/yunshu-OCR/releases/download/models-v1/pdf2md-models-v1.zip"
    assert launcher.MODEL_SIZE == 185346805
    assert launcher.MODEL_SHA256 == "daa85d380551a93f0464950181c3bc29ab16525a55b3a6664108183aa49c9fb0"
```

- [ ] **Step 2: Run the new tests and verify RED**

Run:

```powershell
python -m pytest tests/test_skill_runtime_bootstrap.py -q
```

Expected: FAIL because `_cache_root`, `BootstrapError`, `_script_path`, and `_find_existing_repo` do not exist.

- [ ] **Step 3: Add constants, typed errors, cache policy, and legacy discovery**

At the top of `skills/shared/yunshu_pdf.py`, add the required imports and immutable release metadata:

```python
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import venv
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

RUNTIME_VERSION = "v1.0.0"
SOURCE_URL = "https://github.com/GuMu599/yunshu-OCR/releases/download/v1.0.0/yunshu-OCR-v1.0.0-source.zip"
SOURCE_SIZE = 412019
SOURCE_SHA256 = "4f47c511fe771e80ddecebaf075a00d236ae5daff356290095533402850873a7"
MODEL_URL = "https://github.com/GuMu599/yunshu-OCR/releases/download/models-v1/pdf2md-models-v1.zip"
MODEL_SIZE = 185346805
MODEL_SHA256 = "daa85d380551a93f0464950181c3bc29ab16525a55b3a6664108183aa49c9fb0"
MIN_PYTHON = (3, 10)


class BootstrapError(RuntimeError):
    def __init__(self, code: str, stage: str, message: str, log: Path | None = None):
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.log = log

    def payload(self) -> dict[str, object]:
        data: dict[str, object] = {
            "ok": False,
            "error": self.code,
            "stage": self.stage,
            "message": str(self),
        }
        if self.log is not None:
            data["log"] = str(self.log)
        return data


def _script_path() -> Path:
    return Path(__file__).resolve()


def _is_repo(path: Path) -> bool:
    return (path / "tools" / "pdf-reading" / "pdf2md.py").is_file()


def _cache_root(
    *,
    system: str | None = None,
    env: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    selected_system = system or platform.system()
    selected_env = os.environ if env is None else env
    selected_home = Path.home() if home is None else home
    if selected_system == "Windows":
        base = selected_env.get("LOCALAPPDATA")
        if not base:
            base = str(selected_home / "AppData" / "Local")
        return Path(base) / "yunshu-ocr"
    if selected_system == "Darwin":
        return selected_home / "Library" / "Caches" / "yunshu-ocr"
    return Path(selected_env.get("XDG_CACHE_HOME", selected_home / ".cache")) / "yunshu-ocr"


def _find_existing_repo() -> Path | None:
    override = os.environ.get("YUNSHU_OCR_ROOT")
    if override:
        candidate = Path(override).expanduser().resolve()
        if not _is_repo(candidate):
            raise BootstrapError(
                "override_invalid",
                "resolve",
                f"YUNSHU_OCR_ROOT does not contain tools/pdf-reading/pdf2md.py: {candidate}",
            )
        return candidate
    script = _script_path()
    skill_root = script.parent.parent
    for marker in (
        skill_root / "references" / "yunshu-ocr-root.txt",
        skill_root / ".yunshu-ocr-root",
    ):
        if marker.is_file():
            candidate = Path(marker.read_text(encoding="utf-8").strip()).expanduser().resolve()
            if _is_repo(candidate):
                return candidate
    for parent in script.parents:
        if _is_repo(parent):
            return parent
    return None
```

- [ ] **Step 4: Run the path-policy tests**

Run:

```powershell
python -m pytest tests/test_skill_runtime_bootstrap.py -q
```

Expected: PASS for the four initial tests.

- [ ] **Step 5: Commit runtime policy**

```powershell
git add -- tests/test_skill_runtime_bootstrap.py skills/shared/yunshu_pdf.py
git commit -m "feat: add portable Yunshu runtime policy"
```

### Task 3: Securely download and extract the fixed source release

**Files:**
- Modify: `tests/test_skill_runtime_bootstrap.py`
- Modify: `skills/shared/yunshu_pdf.py`
- Test: `tests/test_skill_runtime_bootstrap.py`

- [ ] **Step 1: Add failing download and archive tests**

Append:

```python
import hashlib
import io
import zipfile


def _source_zip(path: Path, *, unsafe: bool = False) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        name = "../escape.txt" if unsafe else "yunshu-OCR-v1.0.0/tools/pdf-reading/pdf2md.py"
        archive.writestr(name, "print('ok')\n")
        if not unsafe:
            archive.writestr("yunshu-OCR-v1.0.0/requirements.txt", "requests>=2.28\n")
            archive.writestr("yunshu-OCR-v1.0.0/requirements-lock.txt", "requests==2.34.2\n")
            archive.writestr("yunshu-OCR-v1.0.0/pdf2md/__init__.py", "")
            archive.writestr("yunshu-OCR-v1.0.0/models/models.lock.json", "{}")
    return stream.getvalue()


def test_download_rejects_wrong_hash(monkeypatch, tmp_path):
    launcher = _load_launcher()
    payload = b"not-the-release"

    class Response(io.BytesIO):
        headers = {"Content-Length": str(len(payload))}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(launcher.urllib.request, "urlopen", lambda request, timeout: Response(payload))
    with pytest.raises(launcher.BootstrapError) as raised:
        launcher._download_verified("https://example.invalid/source.zip", tmp_path / "source.zip", len(payload), "0" * 64)
    assert raised.value.code == "archive_integrity"
    assert not (tmp_path / "source.zip").exists()


def test_safe_extract_strips_single_release_prefix(tmp_path):
    launcher = _load_launcher()
    payload = _source_zip(tmp_path)
    archive = tmp_path / "source.zip"
    archive.write_bytes(payload)
    target = tmp_path / "runtime"
    launcher._extract_source(archive, target)
    assert (target / "tools" / "pdf-reading" / "pdf2md.py").is_file()
    assert (target / "requirements.txt").is_file()


def test_safe_extract_rejects_parent_traversal(tmp_path):
    launcher = _load_launcher()
    archive = tmp_path / "unsafe.zip"
    archive.write_bytes(_source_zip(tmp_path, unsafe=True))
    with pytest.raises(launcher.BootstrapError) as raised:
        launcher._extract_source(archive, tmp_path / "runtime")
    assert raised.value.code == "archive_unsafe"
    assert not (tmp_path / "escape.txt").exists()
```

- [ ] **Step 2: Run these tests and verify RED**

Run:

```powershell
python -m pytest tests/test_skill_runtime_bootstrap.py -q
```

Expected: FAIL because `_download_verified` and `_extract_source` do not exist.

- [ ] **Step 3: Implement streaming integrity checks and safe extraction**

Add:

```python
def _download_verified(url: str, destination: Path, size: int, sha256: str) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    digest = hashlib.sha256()
    written = 0
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "yunshu-ocr-skill/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > size:
                    raise BootstrapError("archive_integrity", "download", "download exceeded expected size")
                digest.update(chunk)
                output.write(chunk)
        if written != size or digest.hexdigest() != sha256:
            raise BootstrapError(
                "archive_integrity",
                "download",
                f"release verification failed: size={written}, sha256={digest.hexdigest()}",
            )
        os.replace(temporary, destination)
        return destination
    except BootstrapError:
        temporary.unlink(missing_ok=True)
        raise
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise BootstrapError("download_failed", "download", str(exc)) from exc


def _extract_source(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=False)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            if not members:
                raise BootstrapError("archive_unsafe", "extract", "source archive is empty")
            roots = {Path(info.filename.replace("\\", "/")).parts[0] for info in members if info.filename}
            if roots != {"yunshu-OCR-v1.0.0"}:
                raise BootstrapError("archive_unsafe", "extract", f"unexpected archive roots: {sorted(roots)}")
            for info in members:
                normalized = Path(info.filename.replace("\\", "/"))
                parts = normalized.parts
                if normalized.is_absolute() or ".." in parts or len(parts) < 2:
                    raise BootstrapError("archive_unsafe", "extract", f"unsafe ZIP member: {info.filename}")
                if (info.external_attr >> 16) & 0o170000 == 0o120000:
                    raise BootstrapError("archive_unsafe", "extract", f"symlink ZIP member: {info.filename}")
                relative = Path(*parts[1:])
                target = destination / relative
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        required = (
            destination / "tools" / "pdf-reading" / "pdf2md.py",
            destination / "requirements.txt",
            destination / "requirements-lock.txt",
            destination / "pdf2md" / "__init__.py",
            destination / "models" / "models.lock.json",
        )
        missing = [str(path.relative_to(destination)) for path in required if not path.is_file()]
        if missing:
            raise BootstrapError("archive_unsafe", "extract", f"source archive missing: {missing}")
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
```

- [ ] **Step 4: Run the archive tests**

Run:

```powershell
python -m pytest tests/test_skill_runtime_bootstrap.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit secure source acquisition**

```powershell
git add -- tests/test_skill_runtime_bootstrap.py skills/shared/yunshu_pdf.py
git commit -m "feat: verify and safely extract runtime release"
```

### Task 4: Install and reuse the managed runtime

**Files:**
- Modify: `tests/test_skill_runtime_bootstrap.py`
- Modify: `skills/shared/yunshu_pdf.py`
- Test: `tests/test_skill_runtime_bootstrap.py`

- [ ] **Step 1: Add failing dependency, state, and offline reuse tests**

Append tests that avoid production downloads and package installation:

```python
def test_dependency_file_uses_exact_lock_only_for_verified_platform(tmp_path):
    launcher = _load_launcher()
    assert launcher._dependency_file(tmp_path, system="Windows", machine="AMD64", version=(3, 13)) == tmp_path / "requirements-lock.txt"
    assert launcher._dependency_file(tmp_path, system="Darwin", machine="arm64", version=(3, 13)) == tmp_path / "requirements.txt"
    assert launcher._dependency_file(tmp_path, system="Linux", machine="x86_64", version=(3, 12)) == tmp_path / "requirements.txt"


def test_completed_runtime_is_reused_without_download(monkeypatch, tmp_path):
    launcher = _load_launcher()
    paths = launcher._runtime_paths(tmp_path)
    _make_repo(paths.runtime)
    paths.python.parent.mkdir(parents=True)
    paths.python.write_text("python", encoding="utf-8")
    paths.state.parent.mkdir(parents=True)
    paths.state.write_text(json.dumps({
        "runtime_version": launcher.RUNTIME_VERSION,
        "source_sha256": launcher.SOURCE_SHA256,
        "model_sha256": launcher.MODEL_SHA256,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "dependency_mode": launcher._dependency_mode(),
        "models_verified": True,
        "installed_at": 1.0,
    }), encoding="utf-8")
    monkeypatch.setattr(launcher, "_cache_root", lambda: tmp_path)
    monkeypatch.setattr(launcher, "_download_verified", lambda *args, **kwargs: pytest.fail("offline cache must not download"))
    selected = launcher._ensure_managed_runtime()
    assert selected.repo == paths.runtime
    assert selected.python == paths.python


def test_failed_install_does_not_publish_completion_state(monkeypatch, tmp_path):
    launcher = _load_launcher()
    monkeypatch.setattr(launcher, "_cache_root", lambda: tmp_path)
    monkeypatch.setattr(launcher, "_download_verified", lambda *args, **kwargs: (_ for _ in ()).throw(launcher.BootstrapError("download_failed", "download", "offline")))
    with pytest.raises(launcher.BootstrapError):
        launcher._ensure_managed_runtime()
    assert not launcher._runtime_paths(tmp_path).state.exists()
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest tests/test_skill_runtime_bootstrap.py -q
```

Expected: FAIL because `_dependency_file`, `_runtime_paths`, `RuntimeSelection`, and `_ensure_managed_runtime` do not exist.

- [ ] **Step 3: Add versioned paths, state validation, locking, subprocess logging, and install orchestration**

Add these interfaces and behavior to `skills/shared/yunshu_pdf.py`:

```python
@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    runtime: Path
    venv: Path
    python: Path
    state: Path
    source_archive: Path
    log: Path
    lock: Path


@dataclass(frozen=True)
class RuntimeSelection:
    repo: Path
    python: Path


def _runtime_paths(root: Path) -> RuntimePaths:
    py_tag = f"py{sys.version_info.major}{sys.version_info.minor}"
    runtime = root / "runtime" / RUNTIME_VERSION
    environment = root / "venv" / f"{RUNTIME_VERSION}-{py_tag}"
    python = environment / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python")
    return RuntimePaths(
        root=root,
        runtime=runtime,
        venv=environment,
        python=python,
        state=root / "state" / f"{RUNTIME_VERSION}-{py_tag}.json",
        source_archive=root / "downloads" / f"yunshu-OCR-{RUNTIME_VERSION}-source.zip",
        log=root / "logs" / f"bootstrap-{RUNTIME_VERSION}-{py_tag}.log",
        lock=root / "state" / f"{RUNTIME_VERSION}-{py_tag}.lock",
    )


def _dependency_file(repo: Path, *, system: str, machine: str, version: tuple[int, int]) -> Path:
    if system == "Windows" and machine.lower() in {"amd64", "x86_64"} and version == (3, 13):
        return repo / "requirements-lock.txt"
    return repo / "requirements.txt"


def _state_valid(paths: RuntimePaths) -> bool:
    if not (_is_repo(paths.runtime) and paths.python.is_file() and paths.state.is_file()):
        return False
    try:
        state = json.loads(paths.state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    expected = {
        "runtime_version": RUNTIME_VERSION,
        "source_sha256": SOURCE_SHA256,
        "model_sha256": MODEL_SHA256,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "dependency_mode": _dependency_mode(),
        "models_verified": True,
    }
    return all(state.get(key) == value for key, value in expected.items())


def _dependency_mode() -> str:
    locked = (
        platform.system() == "Windows"
        and platform.machine().lower() in {"amd64", "x86_64"}
        and (sys.version_info.major, sys.version_info.minor) == (3, 13)
    )
    return "windows-amd64-py313-lock" if locked else "portable-ranges"


def _run_logged(command: list[str], *, cwd: Path, log: Path, code: str, stage: str) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"$ {' '.join(command)}\n")
        completed = subprocess.run(command, cwd=str(cwd), stdout=handle, stderr=subprocess.STDOUT)
    if completed.returncode != 0:
        raise BootstrapError(code, stage, f"command failed with exit code {completed.returncode}", log)


def _acquire_lock(path: Path, timeout: float = 600.0) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"pid": os.getpid(), "created": time.time()}))
            return
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise BootstrapError("install_busy", "lock", f"runtime install lock timed out: {path}")
            time.sleep(0.25)


def _install_runtime(paths: RuntimePaths) -> None:
    stage_parent = Path(tempfile.mkdtemp(prefix="yunshu-bootstrap-", dir=paths.root))
    stage_runtime = stage_parent / "runtime"
    stage_venv = stage_parent / "venv"
    try:
        _download_verified(SOURCE_URL, paths.source_archive, SOURCE_SIZE, SOURCE_SHA256)
        _extract_source(paths.source_archive, stage_runtime)
        try:
            venv.EnvBuilder(with_pip=True, clear=True).create(stage_venv)
        except Exception as exc:
            raise BootstrapError("venv_failed", "venv", str(exc), paths.log) from exc
        stage_python = stage_venv / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python")
        requirement = _dependency_file(
            stage_runtime,
            system=platform.system(),
            machine=platform.machine(),
            version=(sys.version_info.major, sys.version_info.minor),
        )
        _run_logged([str(stage_python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"], cwd=stage_runtime, log=paths.log, code="dependency_failed", stage="dependencies")
        _run_logged([str(stage_python), "-m", "pip", "install", "-r", str(requirement)], cwd=stage_runtime, log=paths.log, code="dependency_failed", stage="dependencies")
        _run_logged([str(stage_python), "-m", "pdf2md.models", "install", "--source-url", MODEL_URL], cwd=stage_runtime, log=paths.log, code="model_failed", stage="models")
        _run_logged([str(stage_python), "-m", "pdf2md.models", "verify"], cwd=stage_runtime, log=paths.log, code="model_failed", stage="models")
        paths.runtime.parent.mkdir(parents=True, exist_ok=True)
        paths.venv.parent.mkdir(parents=True, exist_ok=True)
        if paths.runtime.exists() or paths.venv.exists():
            raise BootstrapError("runtime_invalid", "publish", "incomplete managed runtime already exists")
        os.replace(stage_runtime, paths.runtime)
        os.replace(stage_venv, paths.venv)
        paths.state.parent.mkdir(parents=True, exist_ok=True)
        state_temporary = paths.state.with_suffix(".tmp")
        state_temporary.write_text(json.dumps({
            "runtime_version": RUNTIME_VERSION,
            "source_sha256": SOURCE_SHA256,
            "model_sha256": MODEL_SHA256,
            "python": f"{sys.version_info.major}.{sys.version_info.minor}",
            "dependency_mode": _dependency_mode(),
            "models_verified": True,
            "installed_at": time.time(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(state_temporary, paths.state)
    finally:
        shutil.rmtree(stage_parent, ignore_errors=True)


def _ensure_managed_runtime() -> RuntimeSelection:
    if sys.version_info < MIN_PYTHON:
        raise BootstrapError("python_unsupported", "preflight", "Python 3.10 or newer is required")
    root = _cache_root()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BootstrapError("cache_unavailable", "preflight", str(exc)) from exc
    paths = _runtime_paths(root)
    if _state_valid(paths):
        return RuntimeSelection(paths.runtime, paths.python)
    _acquire_lock(paths.lock)
    try:
        if not _state_valid(paths):
            paths.state.unlink(missing_ok=True)
            shutil.rmtree(paths.runtime, ignore_errors=True)
            shutil.rmtree(paths.venv, ignore_errors=True)
            _install_runtime(paths)
        if not _state_valid(paths):
            raise BootstrapError("runtime_invalid", "verify", "managed runtime did not pass completion checks", paths.log)
        return RuntimeSelection(paths.runtime, paths.python)
    finally:
        paths.lock.unlink(missing_ok=True)
```

The cleanup occurs only after the lock is held and `_state_valid()` has returned false.
Therefore a completed runtime is never removed. If publication is interrupted after one
directory move, the absent state keeps the partial runtime invalid and the next retry
removes only that version's incomplete runtime and virtual environment before rebuilding.

- [ ] **Step 4: Run the managed-runtime tests**

Run:

```powershell
python -m pytest tests/test_skill_runtime_bootstrap.py -q
```

Expected: PASS without network access.

- [ ] **Step 5: Commit bootstrap orchestration**

```powershell
git add -- tests/test_skill_runtime_bootstrap.py skills/shared/yunshu_pdf.py
git commit -m "feat: bootstrap verified local OCR runtime"
```

### Task 5: Dispatch commands through the selected runtime and report failures

**Files:**
- Modify: `tests/test_skill_runtime_bootstrap.py`
- Modify: `skills/shared/yunshu_pdf.py`
- Test: `tests/test_skill_runtime_bootstrap.py`

- [ ] **Step 1: Add failing dispatch and error-payload tests**

Append:

```python
def test_main_uses_existing_repo_without_bootstrap(monkeypatch, tmp_path):
    launcher = _load_launcher()
    repo = _make_repo(tmp_path / "repo")
    calls = []
    monkeypatch.setattr(launcher, "_find_existing_repo", lambda: repo)
    monkeypatch.setattr(launcher, "_ensure_managed_runtime", lambda: pytest.fail("existing repo must win"))
    monkeypatch.setattr(launcher.subprocess, "run", lambda command, cwd: calls.append((command, cwd)) or type("Result", (), {"returncode": 0})())
    monkeypatch.setattr(launcher.sys, "argv", ["yunshu_pdf.py", "render-page", "paper.pdf", "1"])
    assert launcher.main() == 0
    assert calls[0][0][0] == sys.executable
    assert calls[0][0][1] == str(repo / "tools" / "pdf-reading" / "pdf2md.py")


def test_main_uses_managed_python_when_repo_is_absent(monkeypatch, tmp_path):
    launcher = _load_launcher()
    repo = _make_repo(tmp_path / "runtime")
    python = tmp_path / "venv" / "python"
    calls = []
    monkeypatch.setattr(launcher, "_find_existing_repo", lambda: None)
    monkeypatch.setattr(launcher, "_ensure_managed_runtime", lambda: launcher.RuntimeSelection(repo, python))
    monkeypatch.setattr(launcher.subprocess, "run", lambda command, cwd: calls.append((command, cwd)) or type("Result", (), {"returncode": 0})())
    monkeypatch.setattr(launcher.sys, "argv", ["yunshu_pdf.py", "ensure", "paper.pdf"])
    assert launcher.main() == 0
    assert calls[0][0][0] == str(python)


def test_main_prints_machine_readable_bootstrap_error(monkeypatch, capsys):
    launcher = _load_launcher()
    monkeypatch.setattr(launcher, "_find_existing_repo", lambda: None)
    monkeypatch.setattr(launcher, "_ensure_managed_runtime", lambda: (_ for _ in ()).throw(launcher.BootstrapError("download_failed", "download", "offline")))
    assert launcher.main() == 2
    payload = json.loads(capsys.readouterr().err)
    assert payload == {"ok": False, "error": "download_failed", "stage": "download", "message": "offline"}
```

- [ ] **Step 2: Run the dispatch tests and verify RED**

Run:

```powershell
python -m pytest tests/test_skill_runtime_bootstrap.py -q
```

Expected: FAIL because `main()` still uses the old `_find_repo()` contract and stdout-only error behavior.

- [ ] **Step 3: Replace launcher dispatch with runtime selection**

Implement:

```python
def _select_runtime() -> RuntimeSelection:
    repo = _find_existing_repo()
    if repo is not None:
        return RuntimeSelection(repo=repo, python=Path(sys.executable))
    return _ensure_managed_runtime()


def main() -> int:
    try:
        selected = _select_runtime()
        helper = selected.repo / "tools" / "pdf-reading" / "pdf2md.py"
        completed = subprocess.run(
            [str(selected.python), str(helper), *sys.argv[1:]],
            cwd=str(selected.repo),
        )
        return completed.returncode
    except BootstrapError as exc:
        print(json.dumps(exc.payload(), ensure_ascii=False), file=sys.stderr)
        return 2
```

Delete the old `_find_repo()` and old “reinstall from repository” error payload.

- [ ] **Step 4: Run the complete bootstrap test file**

Run:

```powershell
python -m pytest tests/test_skill_runtime_bootstrap.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit launcher dispatch**

```powershell
git add -- tests/test_skill_runtime_bootstrap.py skills/shared/yunshu_pdf.py
git commit -m "feat: dispatch PDF commands through managed runtime"
```

### Task 6: Update all Skill copies, metadata, and documentation

**Files:**
- Modify: `skills/codex/yunshu-ocr/scripts/yunshu_pdf.py`
- Modify: `skills/claude/yunshu-ocr/scripts/yunshu_pdf.py`
- Modify: `skills/workbuddy/yunshu-ocr/scripts/yunshu_pdf.py`
- Modify: `skills/universal/yunshu-ocr/scripts/yunshu_pdf.py`
- Modify: `skills/workbuddy/yunshu-ocr/SKILL.md`
- Modify: `models/models.lock.json`
- Modify: `README.md`
- Modify: `AI_README.md`
- Modify: `tests/test_skill_packages.py`

- [ ] **Step 1: Copy the verified shared launcher into all four source variants**

Run a formatting-safe mechanical copy:

```powershell
Copy-Item -LiteralPath skills/shared/yunshu_pdf.py -Destination skills/codex/yunshu-ocr/scripts/yunshu_pdf.py -Force
Copy-Item -LiteralPath skills/shared/yunshu_pdf.py -Destination skills/claude/yunshu-ocr/scripts/yunshu_pdf.py -Force
Copy-Item -LiteralPath skills/shared/yunshu_pdf.py -Destination skills/workbuddy/yunshu-ocr/scripts/yunshu_pdf.py -Force
Copy-Item -LiteralPath skills/shared/yunshu_pdf.py -Destination skills/universal/yunshu-ocr/scripts/yunshu_pdf.py -Force
```

- [ ] **Step 2: Change WorkBuddy Skill setup instructions**

Replace the repository-regeneration paragraph in `skills/workbuddy/yunshu-ocr/SKILL.md` with:

```markdown
On first use, the launcher downloads a fixed and SHA-256-verified Yunshu-OCR runtime
and model package into the current user's standard cache. The model download is about
185 MB and initial dependency installation may take several minutes. After setup
succeeds, `ensure`, `locate`, `render`, and `render-page` reuse the local cache and PDF
processing remains offline.

Python 3.10 or newer is required. If setup fails, report the launcher's exact JSON
`error`, `stage`, and `log` fields. Do not ask the user to clone the repository or
regenerate the ZIP. Advanced users may point to an existing valid checkout with
`YUNSHU_OCR_ROOT`.
```

Retain the Token boundary and page-verification chain unchanged.

- [ ] **Step 3: Correct the model release repository**

Change only these fields in `models/models.lock.json`:

```json
"repository": "GuMu599/yunshu-OCR",
"url": "https://github.com/GuMu599/yunshu-OCR/releases/download/models-v1/pdf2md-models-v1.zip"
```

Do not change the asset size, archive SHA-256, model hashes, or licenses.

- [ ] **Step 4: Rewrite human README WorkBuddy setup**

Replace the repository-bound paragraphs near the top of `README.md` with text that states:

```markdown
WorkBuddy 使用上传包：运行命令后得到 `dist/yunshu-ocr-workbuddy.zip`，在 WorkBuddy 中进入
**专家·技能·连接器 → 添加技能 → 上传技能**并选择该文件。上传包不绑定生成机器的仓库路径，
可以复制到其他机器使用。

首次处理 PDF 时，Skill 会在用户缓存目录下载并校验固定版本的 Yunshu-OCR 源码、依赖与约
185 MB 模型包；需要 Python 3.10+、网络连接和足够的磁盘空间。首次安装成功后，PDF 转换、
OCR、Markdown 生成和页码渲染均复用本地缓存并离线执行，不消耗 LLM Token。WorkBuddy
阅读转换结果和生成回答仍可能消耗平台额度。

高级用户可通过 `YUNSHU_OCR_ROOT` 指向现有有效仓库。Windows 已进行实际环境验证；macOS
和 Linux 当前提供跨平台路径兼容与自动化策略测试，在完成真实平台转换验证前不宣称三平台
均已完整验证。
```

- [ ] **Step 5: Rewrite AI README WorkBuddy routing**

Replace the “仓库绑定” bullet in `AI_README.md` with:

```markdown
- **首次运行**：运行包内启动器时，自动下载固定版本、校验 SHA-256、创建隔离环境并安装约
  185 MB 的模型包。首次成功后复用系统用户缓存，正常 PDF 处理保持离线。
- **依赖边界**：需要 Python 3.10+；不要要求用户手动克隆仓库、保留生成机器路径或重新打包。
  高级用户可设置 `YUNSHU_OCR_ROOT` 指向有效仓库。
- **错误处理**：初始化失败时读取并向用户说明 JSON 中的 `error`、`stage` 和 `log`，修复网络、
  Python、权限或依赖问题后重试原命令。
```

Update the permission bullet so it asks only for the PDF, its output directory, the Skill, and the user cache—not a repository directory.

- [ ] **Step 6: Run package, bootstrap, and binding tests**

Run:

```powershell
python -m pytest tests/test_skill_packages.py tests/test_skill_runtime_bootstrap.py tests/test_pdf_reading_helper.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Skill and documentation changes**

```powershell
git add -- skills/codex/yunshu-ocr/scripts/yunshu_pdf.py skills/claude/yunshu-ocr/scripts/yunshu_pdf.py skills/workbuddy/yunshu-ocr/scripts/yunshu_pdf.py skills/universal/yunshu-ocr/scripts/yunshu_pdf.py skills/workbuddy/yunshu-ocr/SKILL.md models/models.lock.json README.md AI_README.md tests/test_skill_packages.py
git commit -m "docs: describe portable WorkBuddy first-use setup"
```

### Task 7: Validate Skill behavior and production artifact

**Files:**
- Verify: `skills/shared/yunshu_pdf.py`
- Verify: `skills/workbuddy/yunshu-ocr/`
- Verify: `dist/yunshu-ocr-workbuddy.zip`
- Verify: repository tests and Git state

- [ ] **Step 1: Run the writing-skills baseline and post-change scenarios**

Use three application scenarios: a WorkBuddy agent receives a PDF on a machine without the repository; a first download fails halfway; and Markdown conflicts with a table on PDF page 7. Record whether the Skill directs the agent to bootstrap, retry safely, reuse offline state, and verify the PDF page without asking the user to clone the repository. The post-change scenarios must follow all four behaviors.

- [ ] **Step 2: Generate a fresh WorkBuddy ZIP**

Run:

```powershell
python skills/install.py workbuddy --force
```

Expected: JSON contains `ok: true`, `variant: workbuddy`, the artifact path, and the upload hint; it does not contain `repository`.

- [ ] **Step 3: Inspect the real ZIP for portability and forbidden files**

Run:

```powershell
python -c "import zipfile,pathlib; p=pathlib.Path('dist/yunshu-ocr-workbuddy.zip'); z=zipfile.ZipFile(p); names=set(z.namelist()); assert names=={'SKILL.md','manifest.yaml','scripts/yunshu_pdf.py'}; text='\n'.join(z.read(n).decode('utf-8') for n in names); forbidden=['yunshu-ocr-root','E:\\\\Codex','C:\\\\Users\\\\GuMu',str(pathlib.Path.cwd().resolve())]; assert not any(x in text for x in forbidden); print({'artifact':str(p.resolve()),'size':p.stat().st_size,'entries':sorted(names)})"
```

Expected: prints artifact metadata and exits 0.

- [ ] **Step 4: Run focused and broad regression checks**

Run:

```powershell
python -m pytest tests/test_skill_packages.py tests/test_skill_runtime_bootstrap.py tests/test_pdf_reading_helper.py -q
python -m pytest pdf2md/tests -q
python -m compileall -q skills tools/pdf-reading pdf2md
git diff --check
```

Expected: all tests pass, compilation exits 0, and `git diff --check` emits no output. If a pre-existing unrelated regression test fails, capture its exact test name and prove it also fails at the pre-change commit before excluding it.

- [ ] **Step 5: Review specification compliance separately from code quality**

Specification review checklist:

```text
[ ] WorkBuddy ZIP has no absolute repository marker or hidden file
[ ] First use obtains fixed source and model releases with SHA-256 checks
[ ] Windows/macOS/Linux cache policy matches the design
[ ] Existing valid repositories and YUNSHU_OCR_ROOT remain supported
[ ] Completed runtime is reused without network access
[ ] PDF/Markdown binding and page fallback behavior are unchanged
[ ] Token claims distinguish local PDF processing from Agent answering
[ ] Documentation does not overclaim real macOS/Linux verification
```

Code-quality review checklist:

```text
[ ] Download and extraction reject oversized, mismatched, traversal, and symlink input
[ ] Failed staging cannot destroy a previously valid runtime
[ ] Error codes and stages are stable and machine-readable
[ ] Tests avoid production network and 185 MB model downloads
[ ] Four committed launcher copies exactly match the shared launcher
[ ] No unrelated refactor or dependency was added
```

- [ ] **Step 6: Commit any verification-driven corrections**

If verification required corrections, stage only the named files and commit:

```powershell
git add -- skills tests README.md AI_README.md models/models.lock.json
git commit -m "fix: harden portable WorkBuddy bootstrap"
```

If no correction was required, do not create an empty commit.

- [ ] **Step 7: Push and verify remote state**

Run:

```powershell
git push origin main
git status --short --branch
git log -3 --oneline --decorate
```

Expected: push succeeds, `main` matches `origin/main`, and the worktree is clean except for an intentionally untracked/ignored generated ZIP if release artifacts are not tracked.
