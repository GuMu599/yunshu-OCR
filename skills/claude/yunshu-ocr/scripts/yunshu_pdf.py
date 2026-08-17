#!/usr/bin/env python3
"""Portable launcher for an installed Yunshu-OCR skill."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import venv
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Mapping


RUNTIME_VERSION = "runtime-v1"
RUNTIME_ARCHIVE_ROOT = "yunshu-OCR-runtime-v1"
RUNTIME_URL = (
    "https://github.com/GuMu599/yunshu-OCR/releases/download/"
    "runtime-v1/yunshu-ocr-runtime-v1.zip"
)
RUNTIME_SIZE = 349674
RUNTIME_SHA256 = "f4f95dbc12ffd060ce662ca1dbc59f2d5b867ccd703183f5f829502e96f84030"
MODEL_URL = (
    "https://github.com/GuMu599/yunshu-OCR/releases/download/"
    "models-v1/pdf2md-models-v1.zip"
)
MODEL_SIZE = 185346805
MODEL_SHA256 = "daa85d380551a93f0464950181c3bc29ab16525a55b3a6664108183aa49c9fb0"
MIN_PYTHON = (3, 10)
INSTALL_LOCK_TIMEOUT = 600.0


class BootstrapError(RuntimeError):
    """A portable runtime setup stage failed without a safe fallback."""

    def __init__(
        self,
        code: str,
        stage: str,
        message: str,
        log: Path | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.log = log

    def payload(self) -> dict[str, object]:
        result: dict[str, object] = {
            "ok": False,
            "error": self.code,
            "stage": self.stage,
            "message": str(self),
        }
        if self.log is not None:
            result["log"] = str(self.log)
        return result


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    runtime: Path
    venv: Path
    python: Path
    state: Path
    archive: Path
    log: Path
    lock: Path


@dataclass(frozen=True)
class RuntimeSelection:
    repo: Path
    python: Path


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
                "YUNSHU_OCR_ROOT does not contain tools/pdf-reading/pdf2md.py: "
                f"{candidate}",
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


def _runtime_paths(root: Path) -> RuntimePaths:
    python_tag = f"py{sys.version_info.major}{sys.version_info.minor}"
    runtime = root / "runtime" / RUNTIME_VERSION
    environment = root / "venv" / f"{RUNTIME_VERSION}-{python_tag}"
    python = environment / (
        "Scripts/python.exe" if platform.system() == "Windows" else "bin/python"
    )
    return RuntimePaths(
        root=root,
        runtime=runtime,
        venv=environment,
        python=python,
        state=root / "state" / f"{RUNTIME_VERSION}-{python_tag}.json",
        archive=root / "downloads" / f"yunshu-ocr-{RUNTIME_VERSION}.zip",
        log=root / "logs" / f"bootstrap-{RUNTIME_VERSION}-{python_tag}.log",
        lock=root / "state" / f"{RUNTIME_VERSION}-{python_tag}.lock",
    )


def _dependency_file(
    repo: Path,
    *,
    system: str,
    machine: str,
    version: tuple[int, int],
) -> Path:
    if (
        system == "Windows"
        and machine.lower() in {"amd64", "x86_64"}
        and version == (3, 13)
    ):
        return repo / "requirements-lock.txt"
    return repo / "requirements.txt"


def _dependency_mode() -> str:
    requirement = _dependency_file(
        Path("."),
        system=platform.system(),
        machine=platform.machine(),
        version=(sys.version_info.major, sys.version_info.minor),
    )
    return (
        "windows-amd64-py313-lock"
        if requirement.name == "requirements-lock.txt"
        else "portable-ranges"
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_matches(path: Path, size: int, sha256: str) -> bool:
    return path.is_file() and path.stat().st_size == size and _file_sha256(path) == sha256


def _download_verified(url: str, destination: Path, size: int, sha256: str) -> Path:
    if _file_matches(destination, size, sha256):
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.unlink(missing_ok=True)
    temporary = destination.with_name(f".{destination.name}.part")
    temporary.unlink(missing_ok=True)
    digest = hashlib.sha256()
    written = 0
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "yunshu-ocr-skill/1.0"},
        )
        with (
            urllib.request.urlopen(request, timeout=60) as response,
            temporary.open("wb") as output,
        ):
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                written += len(chunk)
                if written > size:
                    raise BootstrapError(
                        "archive_integrity",
                        "download",
                        "download exceeded the declared release size",
                    )
                digest.update(chunk)
                output.write(chunk)
        actual_hash = digest.hexdigest()
        if written != size or actual_hash != sha256:
            raise BootstrapError(
                "archive_integrity",
                "download",
                f"release verification failed: size={written}, sha256={actual_hash}",
            )
        os.replace(temporary, destination)
        return destination
    except BootstrapError:
        temporary.unlink(missing_ok=True)
        raise
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise BootstrapError("download_failed", "download", str(exc)) from exc


def _unsafe_member(name: str) -> bool:
    normalized = name.replace("\\", "/")
    posix = PurePosixPath(normalized)
    windows = PureWindowsPath(normalized)
    return (
        not normalized
        or posix.is_absolute()
        or bool(windows.drive)
        or ".." in posix.parts
    )


def _extract_runtime(archive_path: Path, destination: Path) -> None:
    try:
        destination.mkdir(parents=True, exist_ok=False)
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            if not members:
                raise BootstrapError("archive_unsafe", "extract", "runtime archive is empty")
            roots: set[str] = set()
            for info in members:
                if _unsafe_member(info.filename):
                    raise BootstrapError(
                        "archive_unsafe",
                        "extract",
                        f"unsafe ZIP member: {info.filename}",
                    )
                parts = PurePosixPath(info.filename.replace("\\", "/")).parts
                roots.add(parts[0])
                mode = info.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise BootstrapError(
                        "archive_unsafe",
                        "extract",
                        f"symlink ZIP member: {info.filename}",
                    )
            if roots != {RUNTIME_ARCHIVE_ROOT}:
                raise BootstrapError(
                    "archive_unsafe",
                    "extract",
                    f"unexpected runtime archive roots: {sorted(roots)}",
                )

            for info in members:
                parts = PurePosixPath(info.filename.replace("\\", "/")).parts
                if len(parts) == 1:
                    continue
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
        missing = [
            str(path.relative_to(destination))
            for path in required
            if not path.is_file()
        ]
        if missing:
            raise BootstrapError(
                "archive_unsafe",
                "extract",
                f"runtime archive missing required files: {missing}",
            )
    except BootstrapError:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise BootstrapError("archive_unsafe", "extract", str(exc)) from exc


def _state_valid(paths: RuntimePaths) -> bool:
    if not (_is_repo(paths.runtime) and paths.python.is_file() and paths.state.is_file()):
        return False
    try:
        state = json.loads(paths.state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    expected = {
        "runtime_version": RUNTIME_VERSION,
        "runtime_sha256": RUNTIME_SHA256,
        "model_sha256": MODEL_SHA256,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "dependency_mode": _dependency_mode(),
        "models_verified": True,
    }
    return all(state.get(key) == value for key, value in expected.items())


def _run_logged(
    command: list[str],
    *,
    cwd: Path,
    log: Path,
    code: str,
    stage: str,
) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"$ {' '.join(command)}\n")
        completed = subprocess.run(
            command,
            cwd=str(cwd),
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
    if completed.returncode != 0:
        raise BootstrapError(
            code,
            stage,
            f"command failed with exit code {completed.returncode}",
            log,
        )


def _acquire_lock(path: Path, timeout: float = INSTALL_LOCK_TIMEOUT) -> None:
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
                raise BootstrapError(
                    "install_busy",
                    "lock",
                    f"runtime installation is still locked: {path}",
                )
            time.sleep(0.25)


def _write_state(paths: RuntimePaths) -> None:
    paths.state.parent.mkdir(parents=True, exist_ok=True)
    temporary = paths.state.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "runtime_version": RUNTIME_VERSION,
                "runtime_sha256": RUNTIME_SHA256,
                "model_sha256": MODEL_SHA256,
                "python": f"{sys.version_info.major}.{sys.version_info.minor}",
                "dependency_mode": _dependency_mode(),
                "models_verified": True,
                "installed_at": time.time(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    os.replace(temporary, paths.state)


def _install_runtime(paths: RuntimePaths) -> None:
    stage_parent = Path(tempfile.mkdtemp(prefix=".bootstrap-", dir=paths.root))
    stage_runtime = stage_parent / "runtime"
    stage_venv = stage_parent / "venv"
    try:
        archive = _download_verified(
            RUNTIME_URL,
            paths.archive,
            RUNTIME_SIZE,
            RUNTIME_SHA256,
        )
        _extract_runtime(archive, stage_runtime)
        try:
            venv.EnvBuilder(with_pip=True, clear=True).create(stage_venv)
        except Exception as exc:
            raise BootstrapError("venv_failed", "venv", str(exc), paths.log) from exc

        stage_python = stage_venv / (
            "Scripts/python.exe" if platform.system() == "Windows" else "bin/python"
        )
        requirement = _dependency_file(
            stage_runtime,
            system=platform.system(),
            machine=platform.machine(),
            version=(sys.version_info.major, sys.version_info.minor),
        )
        _run_logged(
            [str(stage_python), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"],
            cwd=stage_runtime,
            log=paths.log,
            code="dependency_failed",
            stage="dependencies",
        )
        _run_logged(
            [str(stage_python), "-m", "pip", "install", "-r", str(requirement)],
            cwd=stage_runtime,
            log=paths.log,
            code="dependency_failed",
            stage="dependencies",
        )
        _run_logged(
            [str(stage_python), "-m", "pdf2md.models", "install", "--source-url", MODEL_URL],
            cwd=stage_runtime,
            log=paths.log,
            code="model_failed",
            stage="models",
        )
        _run_logged(
            [str(stage_python), "-m", "pdf2md.models", "verify"],
            cwd=stage_runtime,
            log=paths.log,
            code="model_failed",
            stage="models",
        )

        paths.runtime.parent.mkdir(parents=True, exist_ok=True)
        paths.venv.parent.mkdir(parents=True, exist_ok=True)
        if paths.runtime.exists() or paths.venv.exists():
            raise BootstrapError(
                "runtime_invalid",
                "publish",
                "managed runtime destination is not empty",
                paths.log,
            )
        os.replace(stage_runtime, paths.runtime)
        os.replace(stage_venv, paths.venv)
        _write_state(paths)
    finally:
        shutil.rmtree(stage_parent, ignore_errors=True)


def _ensure_managed_runtime() -> RuntimeSelection:
    if sys.version_info < MIN_PYTHON:
        raise BootstrapError(
            "python_unsupported",
            "preflight",
            "Python 3.10 or newer is required",
        )
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
            raise BootstrapError(
                "runtime_invalid",
                "verify",
                "managed runtime did not pass completion checks",
                paths.log,
            )
        return RuntimeSelection(paths.runtime, paths.python)
    finally:
        paths.lock.unlink(missing_ok=True)


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


if __name__ == "__main__":
    raise SystemExit(main())
