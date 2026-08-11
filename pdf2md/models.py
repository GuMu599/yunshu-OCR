"""Versioned local model inventory for Release installation and conversion."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import tempfile
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_MANIFEST = _REPO_ROOT / "models" / "models.lock.json"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LFS_HEADER = b"version https://git-lfs.github.com/spec/v1"
_INSTALL_COMMAND = "python -m pdf2md.models install"


class ModelManifestError(ValueError):
    """The checked-in model manifest is malformed or unsafe."""


class ModelInstallError(RuntimeError):
    """A Release asset could not be installed without weakening integrity."""


@dataclass(frozen=True)
class ReleaseSpec:
    repository: str
    tag: str
    asset: str
    url: str
    size: int
    sha256: str
    unpacked_size: int


@dataclass(frozen=True)
class ModelFile:
    name: str
    install_path: str
    size: int
    sha256: str
    source: str
    version: str
    license: str


@dataclass(frozen=True)
class ReleaseFile(ModelFile):
    source_path: str


@dataclass(frozen=True)
class ModelManifest:
    path: Path
    repo_root: Path
    schema_version: int
    release: ReleaseSpec
    models: tuple[ModelFile, ...]
    release_files: tuple[ReleaseFile, ...]

    def by_name(self, name: str) -> ModelFile:
        for item in self.models:
            if item.name == name:
                return item
        raise KeyError(f"unknown model: {name}")


def _checked_relative_path(value: object, *, field: str) -> str:
    text = str(value or "")
    pure = PurePosixPath(text)
    if not text or "\\" in text or pure.is_absolute() or ".." in pure.parts:
        raise ModelManifestError(f"{field} must be a normalized repository-relative path: {text!r}")
    normalized = pure.as_posix()
    if normalized != text or normalized in ("", "."):
        raise ModelManifestError(f"{field} must be normalized: {text!r}")
    return normalized


def _checked_sha256(value: object, *, field: str) -> str:
    digest = str(value or "")
    if not _SHA256_RE.fullmatch(digest):
        raise ModelManifestError(f"{field} must be 64 lowercase hexadecimal characters")
    return digest


def _checked_size(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ModelManifestError(f"{field} must be a positive integer")
    return value


def load_manifest(path: str | Path | None = None) -> ModelManifest:
    manifest_path = Path(path or _DEFAULT_MANIFEST).expanduser().resolve()
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelManifestError(f"cannot read model manifest {manifest_path}: {exc}") from exc
    if raw.get("schema_version") != 1:
        raise ModelManifestError("schema_version must be 1")

    release_raw = raw.get("release")
    if not isinstance(release_raw, dict):
        raise ModelManifestError("release must be an object")
    release = ReleaseSpec(
        repository=str(release_raw.get("repository") or ""),
        tag=str(release_raw.get("tag") or ""),
        asset=_checked_relative_path(release_raw.get("asset"), field="release.asset"),
        url=str(release_raw.get("url") or ""),
        size=_checked_size(release_raw.get("size"), field="release.size"),
        sha256=_checked_sha256(release_raw.get("sha256"), field="release.sha256"),
        unpacked_size=_checked_size(
            release_raw.get("unpacked_size"), field="release.unpacked_size"
        ),
    )
    if not release.repository or not release.tag or release.tag == "latest":
        raise ModelManifestError("release must use a repository and fixed non-latest tag")
    if release.tag not in release.url or release.asset not in release.url or "latest" in release.url.lower():
        raise ModelManifestError("release.url must point to the fixed tag and asset")

    model_rows = raw.get("models")
    if not isinstance(model_rows, list) or not model_rows:
        raise ModelManifestError("models must be a non-empty array")
    models: list[ModelFile] = []
    names: set[str] = set()
    paths: set[str] = set()
    for index, row in enumerate(model_rows):
        if not isinstance(row, dict):
            raise ModelManifestError(f"models[{index}] must be an object")
        name = str(row.get("name") or "")
        install_path = _checked_relative_path(
            row.get("install_path"), field=f"models[{index}].install_path"
        )
        if not name or name in names:
            raise ModelManifestError(f"duplicate or empty model name: {name!r}")
        if install_path in paths:
            raise ModelManifestError(f"duplicate model install_path: {install_path!r}")
        names.add(name)
        paths.add(install_path)
        models.append(
            ModelFile(
                name=name,
                install_path=install_path,
                size=_checked_size(row.get("size"), field=f"models[{index}].size"),
                sha256=_checked_sha256(
                    row.get("sha256"), field=f"models[{index}].sha256"
                ),
                source=str(row.get("source") or ""),
                version=str(row.get("version") or ""),
                license=str(row.get("license") or ""),
            )
        )
    if any(not item.source or not item.version or not item.license for item in models):
        raise ModelManifestError("every model needs source, version, and license metadata")

    release_file_rows = raw.get("release_files", [])
    if not isinstance(release_file_rows, list):
        raise ModelManifestError("release_files must be an array")
    release_files: list[ReleaseFile] = []
    for index, row in enumerate(release_file_rows):
        if not isinstance(row, dict):
            raise ModelManifestError(f"release_files[{index}] must be an object")
        name = str(row.get("name") or "")
        install_path = _checked_relative_path(
            row.get("install_path"), field=f"release_files[{index}].install_path"
        )
        source_path = _checked_relative_path(
            row.get("source_path"), field=f"release_files[{index}].source_path"
        )
        if not name or name in names:
            raise ModelManifestError(f"duplicate or empty release file name: {name!r}")
        if install_path in paths:
            raise ModelManifestError(f"duplicate release file install_path: {install_path!r}")
        names.add(name)
        paths.add(install_path)
        release_files.append(
            ReleaseFile(
                name=name,
                install_path=install_path,
                source_path=source_path,
                size=_checked_size(row.get("size"), field=f"release_files[{index}].size"),
                sha256=_checked_sha256(
                    row.get("sha256"), field=f"release_files[{index}].sha256"
                ),
                source=str(row.get("source") or ""),
                version=str(row.get("version") or ""),
                license=str(row.get("license") or ""),
            )
        )
    if any(
        not item.source or not item.version or not item.license
        for item in release_files
    ):
        raise ModelManifestError("every release file needs source, version, and license metadata")
    declared_size = sum(item.size for item in (*models, *release_files))
    if declared_size != release.unpacked_size:
        raise ModelManifestError("release.unpacked_size must equal all declared file sizes")

    return ModelManifest(
        path=manifest_path,
        repo_root=manifest_path.parent.parent,
        schema_version=1,
        release=release,
        models=tuple(models),
        release_files=tuple(release_files),
    )


def model_path(name: str, manifest: ModelManifest | None = None) -> Path:
    selected = manifest or load_manifest()
    return (selected.repo_root / selected.by_name(name).install_path).resolve()


def _installed_path(item: ModelFile, selected: ModelManifest) -> Path:
    return (selected.repo_root / item.install_path).resolve()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_status(path: Path, item: ModelFile) -> dict:
    state = {"name": item.name, "path": str(path), "expected_sha256": item.sha256}
    if not path.is_file():
        return {**state, "status": "missing", "available": False}
    with path.open("rb") as handle:
        header = handle.read(len(_LFS_HEADER))
    if header == _LFS_HEADER:
        return {**state, "status": "git_lfs_pointer", "available": False}
    actual_size = path.stat().st_size
    if actual_size != item.size:
        return {
            **state,
            "status": "wrong_size",
            "available": False,
            "size": actual_size,
            "expected_size": item.size,
        }
    actual_sha256 = file_sha256(path)
    if actual_sha256 != item.sha256:
        return {
            **state,
            "status": "wrong_hash",
            "available": False,
            "sha256": actual_sha256,
        }
    return {
        **state,
        "status": "verified",
        "available": True,
        "size": actual_size,
        "sha256": actual_sha256,
    }


def verify_models(manifest: ModelManifest | None = None) -> dict:
    selected = manifest or load_manifest()
    states = [_file_status(model_path(item.name, selected), item) for item in selected.models]
    release_file_states = [
        _file_status(_installed_path(item, selected), item)
        for item in selected.release_files
    ]
    available = all(state["available"] for state in (*states, *release_file_states))
    result = {
        "available": available,
        "manifest": str(selected.path),
        "release_tag": selected.release.tag,
        "models": states,
        "release_files": release_file_states,
    }
    if not available:
        result["error"] = f"model_missing_or_invalid; run: {_INSTALL_COMMAND}"
    return result


def model_status(manifest: ModelManifest | None = None) -> dict:
    return verify_models(manifest)


def _download_release(selected: ModelManifest, temp_dir: Path, source_url: str | None) -> Path:
    url = source_url or selected.release.url
    target = temp_dir / selected.release.asset
    maximum = selected.release.size
    try:
        with urllib.request.urlopen(url, timeout=30) as response, target.open("wb") as output:
            declared_length = response.headers.get("Content-Length")
            if declared_length is not None and int(declared_length) > maximum:
                raise ModelInstallError("archive_too_large: Content-Length exceeds manifest")
            total = 0
            while True:
                chunk = response.read(min(1024 * 1024, maximum + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > maximum:
                    raise ModelInstallError("archive_too_large: download exceeds manifest")
                output.write(chunk)
    except ModelInstallError:
        raise
    except (OSError, urllib.error.URLError, ValueError) as exc:
        raise ModelInstallError(f"download_failed: {url}: {exc}") from exc
    return target


def _verify_archive(path: Path, release: ReleaseSpec) -> None:
    actual_size = path.stat().st_size
    if actual_size != release.size:
        raise ModelInstallError(
            f"archive_integrity: expected {release.size} bytes, got {actual_size}"
        )
    actual_sha256 = file_sha256(path)
    if actual_sha256 != release.sha256:
        raise ModelInstallError(
            f"archive_integrity: expected SHA-256 {release.sha256}, got {actual_sha256}"
        )


def _safe_member_name(name: str) -> str:
    if re.match(r"^[A-Za-z]:/", name):
        raise ModelInstallError(f"unsafe_archive: drive path: {name!r}")
    try:
        return _checked_relative_path(name, field="archive member")
    except ModelManifestError as exc:
        raise ModelInstallError(f"unsafe_archive: {exc}") from exc


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def _extract_declared_members(
    archive: Path,
    selected: ModelManifest,
    stage_root: Path,
) -> None:
    declared = {
        item.install_path: item for item in (*selected.models, *selected.release_files)
    }
    seen: set[str] = set()
    expanded = 0
    try:
        bundle = zipfile.ZipFile(archive)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ModelInstallError(f"unsafe_archive: invalid ZIP: {exc}") from exc
    with bundle:
        for info in bundle.infolist():
            name = _safe_member_name(info.filename)
            if name in seen:
                raise ModelInstallError(f"unsafe_archive: duplicate member: {name}")
            seen.add(name)
            if _is_symlink(info):
                raise ModelInstallError(f"unsafe_archive: symlink member: {name}")
            if info.is_dir():
                raise ModelInstallError(f"undeclared directory member: {name}")
            item = declared.get(name)
            if item is None:
                raise ModelInstallError(f"undeclared archive member: {name}")
            expanded += info.file_size
            if expanded > selected.release.unpacked_size:
                raise ModelInstallError("unsafe_archive: expanded size exceeds manifest")
            if info.file_size != item.size:
                raise ModelInstallError(
                    f"model_integrity:{item.name}: expected {item.size} bytes, got {info.file_size}"
                )
            target = stage_root / Path(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, target.open("wb") as output:
                remaining = item.size
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ModelInstallError(f"model_integrity:{item.name}: truncated member")
                    output.write(chunk)
                    remaining -= len(chunk)
                if source.read(1):
                    raise ModelInstallError(f"model_integrity:{item.name}: oversized member")
        missing = sorted(set(declared) - seen)
        if missing:
            raise ModelInstallError(f"model_integrity: missing archive members: {missing}")
        if expanded != selected.release.unpacked_size:
            raise ModelInstallError("model_integrity: expanded size does not match manifest")


def _verify_staged_models(stage_root: Path, selected: ModelManifest) -> None:
    for item in (*selected.models, *selected.release_files):
        state = _file_status(stage_root / item.install_path, item)
        if not state["available"]:
            raise ModelInstallError(f"model_integrity:{item.name}:{state['status']}")


def _publish_with_rollback(stage_root: Path, selected: ModelManifest, backup_root: Path) -> None:
    processed: list[tuple[Path, Path | None]] = []
    try:
        for item in (*selected.models, *selected.release_files):
            source = stage_root / item.install_path
            target = _installed_path(item, selected)
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = None
            if target.exists():
                backup = backup_root / item.install_path
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, backup)
            processed.append((target, backup))
            os.replace(source, target)
    except OSError as exc:
        for target, backup in reversed(processed):
            try:
                if target.exists():
                    target.unlink()
                if backup is not None and backup.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(backup, target)
            except OSError:
                pass
        raise ModelInstallError(f"publish_failed: {exc}") from exc


def install_models(
    manifest: ModelManifest | None = None,
    *,
    source_url: str | None = None,
) -> dict:
    selected = manifest or load_manifest()
    selected.repo_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".model-install-", dir=selected.repo_root) as temp:
        temp_root = Path(temp)
        archive = _download_release(selected, temp_root, source_url)
        _verify_archive(archive, selected.release)
        stage_root = temp_root / "stage"
        _extract_declared_members(archive, selected, stage_root)
        _verify_staged_models(stage_root, selected)
        _publish_with_rollback(stage_root, selected, temp_root / "backup")
    result = verify_models(selected)
    if not result["available"]:
        raise ModelInstallError(f"publish_failed: {result['error']}")
    return result


def _legacy_model_path(name: str) -> Path | None:
    if name == "layout":
        return (
            Path(os.environ.get("USERPROFILE", "C:/Users/GuMu"))
            / "AppData/Local/datalab/datalab/Cache/models/Layout/YOLO"
            / "doclayout_yolo_docstructbench_imgsz1280_2501.pt"
        ).resolve()
    if name in ("pix2tex_weights", "pix2tex_resizer"):
        spec = importlib.util.find_spec("pix2tex")
        if spec is None or not spec.submodule_search_locations:
            return None
        package = Path(next(iter(spec.submodule_search_locations)))
        filename = "weights.pth" if name == "pix2tex_weights" else "image_resizer.pth"
        return (package / "model" / "checkpoints" / filename).resolve()
    return None


def _build_source_path(
    item: ModelFile,
    selected: ModelManifest,
    source_root: Path | None,
) -> Path:
    candidates: list[Path] = []
    if source_root is not None:
        candidates.append(source_root / item.install_path)
    candidates.append(model_path(item.name, selected))
    legacy = _legacy_model_path(item.name)
    if legacy is not None:
        candidates.append(legacy)
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def _release_file_source_path(item: ReleaseFile, selected: ModelManifest) -> Path:
    return (selected.repo_root / item.source_path).resolve()


def build_release_archive(
    output: str | Path,
    manifest: ModelManifest | None = None,
    *,
    source_root: str | Path | None = None,
) -> dict:
    selected = manifest or load_manifest()
    root = Path(source_root).expanduser().resolve() if source_root else None
    output_path = Path(output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_name(f".{output_path.name}.tmp")
    if temp_path.exists():
        temp_path.unlink()
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_STORED) as bundle:
            declared = (*selected.models, *selected.release_files)
            for item in sorted(declared, key=lambda value: value.install_path):
                if isinstance(item, ReleaseFile):
                    source = _release_file_source_path(item, selected)
                else:
                    source = _build_source_path(item, selected, root)
                state = _file_status(source, item)
                if not state["available"]:
                    raise ModelInstallError(
                        f"model_integrity:{item.name}:{state['status']}:{source}"
                    )
                info = zipfile.ZipInfo(item.install_path, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_STORED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | 0o644) << 16
                with source.open("rb") as handle:
                    bundle.writestr(info, handle.read())
        os.replace(temp_path, output_path)
    except Exception:
        if temp_path.exists():
            temp_path.unlink()
        raise
    return {
        "path": str(output_path),
        "size": output_path.stat().st_size,
        "sha256": file_sha256(output_path),
        "models": [item.name for item in selected.models],
        "release_files": [item.name for item in selected.release_files],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install and verify yunshu-OCR Release models")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "verify"):
        command = commands.add_parser(name, help=f"{name} local model files")
        command.add_argument("--manifest", default=None, help="model manifest path")
    install = commands.add_parser("install", help="download and install verified Release models")
    install.add_argument("--manifest", default=None, help="model manifest path")
    install.add_argument("--source-url", default=None, help="override Release URL")
    build = commands.add_parser("build-release", help="build a deterministic Release ZIP")
    build.add_argument("--manifest", default=None, help="model manifest path")
    build.add_argument("--output", required=True, help="output ZIP path")
    build.add_argument("--source-root", default=None, help="root containing manifest install paths")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        if args.command in ("status", "verify"):
            result = verify_models(manifest)
            code = 0 if result["available"] else 1
        elif args.command == "install":
            result = install_models(manifest, source_url=args.source_url)
            code = 0
        else:
            result = build_release_archive(
                args.output,
                manifest,
                source_root=args.source_root,
            )
            code = 0
    except (ModelManifestError, ModelInstallError, OSError) as exc:
        print(json.dumps({"available": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
