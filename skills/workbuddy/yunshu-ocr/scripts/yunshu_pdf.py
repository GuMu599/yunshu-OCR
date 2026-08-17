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
import uuid
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
MODEL_MANIFEST_SHA256 = (
    "6b5b93e645ab682546001000341cc91a3893fad68dd42732c21899c746b393a3"
)
MIN_PYTHON = (3, 10)
INSTALL_LOCK_TIMEOUT = 600.0
RUNTIME_ALLOWED_FILES = {
    "LICENSE",
    "NOTICE",
    "requirements.txt",
    "requirements-lock.txt",
    "models/models.lock.json",
}
RUNTIME_ALLOWED_PREFIXES = (
    "pdf2md/",
    "tools/pdf-reading/",
    "models/production/",
    "THIRD_PARTY_LICENSES/",
)


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
    journal: Path


@dataclass(frozen=True)
class RuntimeSelection:
    repo: Path
    python: Path
    log: Path | None = None


@dataclass(frozen=True)
class LockOwnership:
    token: str | None
    pid: int | None
    content: bytes
    identity: tuple[int, int, int, int]
    modified_ns: int


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
    xdg_cache = selected_env.get("XDG_CACHE_HOME", "")
    base = (
        Path(xdg_cache)
        if xdg_cache and PurePosixPath(xdg_cache).is_absolute()
        else selected_home / ".cache"
    )
    return base / "yunshu-ocr"


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
            candidate = (
                Path(marker.read_text(encoding="utf-8").strip()).expanduser().resolve()
            )
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
        journal=root / "state" / f"{RUNTIME_VERSION}-{python_tag}.publishing.json",
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
    return (
        path.is_file() and path.stat().st_size == size and _file_sha256(path) == sha256
    )


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


def _runtime_member_declared(parts: tuple[str, ...]) -> bool:
    if len(parts) == 1:
        return True
    relative = "/".join(parts[1:]).rstrip("/")
    if relative in RUNTIME_ALLOWED_FILES:
        return True
    if any(f"{relative}/" == prefix for prefix in RUNTIME_ALLOWED_PREFIXES):
        return True
    if any(relative.startswith(prefix) for prefix in RUNTIME_ALLOWED_PREFIXES):
        return True
    allowed = (*RUNTIME_ALLOWED_FILES, *RUNTIME_ALLOWED_PREFIXES)
    return any(item.startswith(f"{relative}/") for item in allowed)


def _extract_runtime(archive_path: Path, destination: Path) -> None:
    try:
        destination.mkdir(parents=True, exist_ok=False)
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            if not members:
                raise BootstrapError(
                    "archive_unsafe", "extract", "runtime archive is empty"
                )
            roots: set[str] = set()
            seen_members: dict[str, str] = {}
            for info in members:
                if _unsafe_member(info.filename):
                    raise BootstrapError(
                        "archive_unsafe",
                        "extract",
                        f"unsafe ZIP member: {info.filename}",
                    )
                parts = PurePosixPath(info.filename.replace("\\", "/")).parts
                normalized = "/".join(parts).rstrip("/")
                collision_key = normalized.casefold()
                if collision_key in seen_members:
                    raise BootstrapError(
                        "archive_unsafe",
                        "extract",
                        "duplicate or case-colliding ZIP members: "
                        f"{seen_members[collision_key]} and {info.filename}",
                    )
                seen_members[collision_key] = info.filename
                roots.add(parts[0])
                if not _runtime_member_declared(parts):
                    raise BootstrapError(
                        "archive_unsafe",
                        "extract",
                        f"undeclared runtime ZIP member: {info.filename}",
                    )
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


def _model_inventory(repo: Path) -> list[tuple[Path, int, str]] | None:
    manifest = repo / "models" / "models.lock.json"
    try:
        if _file_sha256(manifest) != MODEL_MANIFEST_SHA256:
            return None
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        models = payload["models"]
        release_files = payload["release_files"]
    except (OSError, KeyError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(models, list) or not isinstance(release_files, list):
        return None
    declared = [*models, *release_files]
    if not declared:
        return None
    inventory: list[tuple[Path, int, str]] = []
    for item in declared:
        try:
            raw_path = str(item["install_path"])
            expected_size = int(item["size"])
            expected_hash = str(item["sha256"]).lower()
        except (KeyError, TypeError, ValueError):
            return None
        if len(expected_hash) != 64 or any(
            character not in "0123456789abcdef" for character in expected_hash
        ):
            return None
        relative = PurePosixPath(raw_path.replace("\\", "/"))
        if (
            relative.is_absolute()
            or PureWindowsPath(raw_path).drive
            or ".." in relative.parts
        ):
            return None
        inventory.append((Path(*relative.parts), expected_size, expected_hash))
    return inventory


def _model_metadata_fingerprint(repo: Path) -> str | None:
    inventory = _model_inventory(repo)
    if inventory is None:
        return None
    metadata = []
    try:
        for relative, expected_size, expected_hash in inventory:
            current = (repo / relative).stat()
            metadata.append(
                (
                    relative.as_posix(),
                    expected_size,
                    expected_hash,
                    current.st_size,
                    current.st_mtime_ns,
                )
            )
    except OSError:
        return None
    encoded = json.dumps(metadata, separators=(",", ":"), ensure_ascii=True).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _models_present(repo: Path) -> bool:
    inventory = _model_inventory(repo)
    if inventory is None:
        return False
    for relative, expected_size, expected_hash in inventory:
        target = repo / relative
        try:
            if not _file_matches(target, expected_size, expected_hash):
                return False
        except OSError:
            return False
    return True


def _state_valid(paths: RuntimePaths) -> bool:
    if not (
        _is_repo(paths.runtime) and paths.python.is_file() and paths.state.is_file()
    ):
        return False
    try:
        state = json.loads(paths.state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    expected = {
        "runtime_version": RUNTIME_VERSION,
        "runtime_sha256": RUNTIME_SHA256,
        "model_sha256": MODEL_SHA256,
        "model_manifest_sha256": MODEL_MANIFEST_SHA256,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "dependency_mode": _dependency_mode(),
        "models_verified": True,
    }
    if not all(state.get(key) == value for key, value in expected.items()):
        return False
    fingerprint = _model_metadata_fingerprint(paths.runtime)
    return (
        fingerprint is not None
        and state.get("model_metadata_fingerprint") == fingerprint
    )


def _run_logged(
    command: list[str],
    *,
    cwd: Path,
    log: Path,
    code: str,
    stage: str,
) -> None:
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"$ {' '.join(command)}\n")
            completed = subprocess.run(
                command,
                cwd=str(cwd),
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
    except OSError as exc:
        raise BootstrapError(code, stage, str(exc), log) from exc
    if completed.returncode != 0:
        raise BootstrapError(
            code,
            stage,
            f"command failed with exit code {completed.returncode}",
            log,
        )


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if os.name == "nt":
        import ctypes

        process_query_limited_information = 0x1000
        error_access_denied = 5
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.OpenProcess(
            process_query_limited_information,
            False,
            pid,
        )
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return ctypes.get_last_error() == error_access_denied
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _observe_lock(path: Path) -> LockOwnership | None:
    try:
        with path.open("rb") as handle:
            content = handle.read()
            metadata = os.fstat(handle.fileno())
    except OSError:
        return None
    token = None
    pid = None
    try:
        payload = json.loads(content.decode("utf-8"))
        raw_token = payload.get("token")
        if isinstance(raw_token, str):
            token = raw_token
        pid = int(payload["pid"])
    except (UnicodeDecodeError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        pass
    return LockOwnership(
        token,
        pid,
        content,
        (metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns),
        metadata.st_mtime_ns,
    )


def _remove_lock_if_matches(path: Path, observed: LockOwnership | None) -> bool:
    if observed is None or _observe_lock(path) != observed:
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True


def _release_lock(path: Path, ownership: LockOwnership) -> None:
    _remove_lock_if_matches(path, ownership)


def _acquire_lock(path: Path, timeout: float = INSTALL_LOCK_TIMEOUT) -> LockOwnership:
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        token = uuid.uuid4().hex
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {"pid": os.getpid(), "created": time.time(), "token": token}
                    )
                )
                handle.flush()
                os.fsync(handle.fileno())
            ownership = _observe_lock(path)
            if ownership is not None and ownership.token == token:
                return ownership
        except FileExistsError:
            observed = _observe_lock(path)
            if observed is None:
                continue
            owner_alive = _pid_alive(observed.pid) if observed.pid is not None else None
            invalid_age = time.time() - observed.modified_ns / 1_000_000_000
            if owner_alive is False or (owner_alive is None and invalid_age >= 5.0):
                if _remove_lock_if_matches(path, observed):
                    continue
            if time.monotonic() >= deadline:
                raise BootstrapError(
                    "install_busy",
                    "lock",
                    f"runtime installation is still locked: {path}",
                )
            time.sleep(0.25)


def _cleanup_staging(root: Path) -> None:
    for candidate in root.glob(".bootstrap-*"):
        if candidate.is_dir():
            shutil.rmtree(candidate, ignore_errors=True)


def _write_publish_journal(paths: RuntimePaths, stage: Path) -> None:
    resolved_stage = stage.resolve()
    if (
        resolved_stage.parent != paths.root.resolve()
        or not resolved_stage.name.startswith(".bootstrap-")
    ):
        raise BootstrapError(
            "runtime_invalid",
            "publish",
            f"invalid runtime staging directory: {stage}",
            paths.log,
        )
    paths.journal.parent.mkdir(parents=True, exist_ok=True)
    temporary = paths.journal.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "stage": resolved_stage.name,
                "runtime_version": RUNTIME_VERSION,
                "runtime_sha256": RUNTIME_SHA256,
                "model_sha256": MODEL_SHA256,
                "model_manifest_sha256": MODEL_MANIFEST_SHA256,
                "python": f"{sys.version_info.major}.{sys.version_info.minor}",
                "dependency_mode": _dependency_mode(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    os.replace(temporary, paths.journal)


def _read_publish_journal(paths: RuntimePaths) -> Path | None:
    try:
        payload = json.loads(paths.journal.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    expected = {
        "runtime_version": RUNTIME_VERSION,
        "runtime_sha256": RUNTIME_SHA256,
        "model_sha256": MODEL_SHA256,
        "model_manifest_sha256": MODEL_MANIFEST_SHA256,
        "python": f"{sys.version_info.major}.{sys.version_info.minor}",
        "dependency_mode": _dependency_mode(),
    }
    if not all(payload.get(key) == value for key, value in expected.items()):
        return None
    stage_name = payload.get("stage")
    if not isinstance(stage_name, str) or not stage_name.startswith(".bootstrap-"):
        return None
    stage = (paths.root / stage_name).resolve()
    return stage if stage.parent == paths.root.resolve() else None


def _write_state(paths: RuntimePaths) -> None:
    fingerprint = _model_metadata_fingerprint(paths.runtime)
    if fingerprint is None:
        raise BootstrapError(
            "runtime_invalid",
            "verify",
            "managed runtime model inventory is incomplete",
            paths.log,
        )
    paths.state.parent.mkdir(parents=True, exist_ok=True)
    temporary = paths.state.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {
                "runtime_version": RUNTIME_VERSION,
                "runtime_sha256": RUNTIME_SHA256,
                "model_sha256": MODEL_SHA256,
                "model_manifest_sha256": MODEL_MANIFEST_SHA256,
                "model_metadata_fingerprint": fingerprint,
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


def _runtime_complete(runtime: Path, python: Path) -> bool:
    return _is_repo(runtime) and python.is_file() and _models_present(runtime)


def _recover_interrupted_publish(paths: RuntimePaths) -> bool:
    stage = _read_publish_journal(paths)
    if stage is None:
        return False
    staged_runtime, staged_venv = stage / "runtime", stage / "venv"
    python_relative = paths.python.relative_to(paths.venv)
    runtime_candidate = paths.runtime if paths.runtime.is_dir() else staged_runtime
    venv_candidate = paths.venv if paths.venv.is_dir() else staged_venv
    if not _runtime_complete(runtime_candidate, venv_candidate / python_relative):
        return False
    try:
        paths.runtime.parent.mkdir(parents=True, exist_ok=True)
        paths.venv.parent.mkdir(parents=True, exist_ok=True)
        if runtime_candidate != paths.runtime:
            if paths.runtime.exists():
                return False
            os.replace(runtime_candidate, paths.runtime)
        if venv_candidate != paths.venv:
            if paths.venv.exists():
                return False
            os.replace(venv_candidate, paths.venv)
        if not _runtime_complete(paths.runtime, paths.python):
            return False
        _write_state(paths)
        paths.journal.unlink(missing_ok=True)
        shutil.rmtree(stage, ignore_errors=True)
        return True
    except OSError as exc:
        raise BootstrapError("runtime_invalid", "publish", str(exc), paths.log) from exc


def _reconstruct_state(paths: RuntimePaths) -> bool:
    if not _runtime_complete(paths.runtime, paths.python):
        return False
    _write_state(paths)
    return True


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
            [
                str(stage_python),
                "-m",
                "pip",
                "install",
                "--upgrade",
                "pip",
                "setuptools",
                "wheel",
            ],
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
            [
                str(stage_python),
                "-m",
                "pdf2md.models",
                "install",
                "--source-url",
                MODEL_URL,
            ],
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
        if not _runtime_complete(stage_runtime, stage_python):
            raise BootstrapError(
                "runtime_invalid",
                "verify",
                "installed runtime did not pass model inventory verification",
                paths.log,
            )
        _write_publish_journal(paths, stage_parent)
        try:
            os.replace(stage_runtime, paths.runtime)
            os.replace(stage_venv, paths.venv)
            _write_state(paths)
            paths.journal.unlink(missing_ok=True)
        except OSError as exc:
            raise BootstrapError(
                "runtime_invalid", "publish", str(exc), paths.log
            ) from exc
    finally:
        shutil.rmtree(stage_parent, ignore_errors=True)


def _require_supported_python() -> None:
    if sys.version_info < MIN_PYTHON:
        raise BootstrapError(
            "python_unsupported",
            "preflight",
            "Python 3.10 or newer is required",
        )


def _ensure_managed_runtime() -> RuntimeSelection:
    _require_supported_python()
    try:
        root = _cache_root()
        root.mkdir(parents=True, exist_ok=True)
        paths = _runtime_paths(root)
        if _state_valid(paths):
            return RuntimeSelection(paths.runtime, paths.python, paths.log)

        ownership = _acquire_lock(paths.lock)
        try:
            if _state_valid(paths):
                return RuntimeSelection(paths.runtime, paths.python, paths.log)
            if _recover_interrupted_publish(paths) or _reconstruct_state(paths):
                return RuntimeSelection(paths.runtime, paths.python, paths.log)
            paths.journal.unlink(missing_ok=True)
            _cleanup_staging(paths.root)
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
            return RuntimeSelection(paths.runtime, paths.python, paths.log)
        finally:
            _release_lock(paths.lock, ownership)
    except BootstrapError:
        raise
    except OSError as exc:
        raise BootstrapError("cache_unavailable", "cache", str(exc)) from exc


def _select_runtime() -> RuntimeSelection:
    _require_supported_python()
    repo = _find_existing_repo()
    if repo is not None:
        return RuntimeSelection(repo=repo, python=Path(sys.executable))
    return _ensure_managed_runtime()


def main() -> int:
    try:
        selected = _select_runtime()
        helper = selected.repo / "tools" / "pdf-reading" / "pdf2md.py"
        command = [str(selected.python), str(helper), *sys.argv[1:]]
        try:
            completed = subprocess.run(command, cwd=str(selected.repo))
        except OSError as exc:
            if selected.log is not None:
                try:
                    selected.log.parent.mkdir(parents=True, exist_ok=True)
                    with selected.log.open("a", encoding="utf-8") as handle:
                        handle.write(f"$ {' '.join(command)}\n")
                        handle.write(f"dispatch failed: {exc}\n")
                except OSError:
                    pass
            raise BootstrapError(
                "helper_failed", "dispatch", str(exc), selected.log
            ) from exc
        return completed.returncode
    except BootstrapError as exc:
        print(json.dumps(exc.payload(), ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
