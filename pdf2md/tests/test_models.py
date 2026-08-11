"""Versioned model manifest, verification, installation, and release building."""

from __future__ import annotations

import hashlib
import json
import stat
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pdf2md import models as model_assets  # noqa: E402


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_test_manifest(
    tmp_path: Path,
    *,
    files: dict[str, bytes] | None = None,
    declared: dict[str, bytes] | None = None,
) -> model_assets.ModelManifest:
    repo = tmp_path / "repo"
    manifest_dir = repo / "models"
    manifest_dir.mkdir(parents=True)
    declared = declared or {"layout": b"layout-model"}
    entries = []
    for name, content in declared.items():
        entries.append(
            {
                "name": name,
                "install_path": f"models/runtime/{name}.bin",
                "size": len(content),
                "sha256": _sha256(content),
                "source": "test",
                "version": "1",
                "license": "MIT",
            }
        )
    manifest_data = {
        "schema_version": 1,
        "release": {
            "repository": "owner/repo",
            "tag": "models-v1",
            "asset": "models.zip",
            "url": "https://github.com/owner/repo/releases/download/models-v1/models.zip",
            "size": 1,
            "sha256": "0" * 64,
            "unpacked_size": sum(len(value) for value in declared.values()),
        },
        "models": entries,
    }
    manifest_path = manifest_dir / "models.lock.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
    for name, content in (files or {}).items():
        target = repo / f"models/runtime/{name}.bin"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return model_assets.load_manifest(manifest_path)


def make_release(
    tmp_path: Path,
    *,
    member_name: str = "models/runtime/layout.bin",
    model_content: bytes = b"release-layout",
    declared_content: bytes | None = None,
    extra_member: str | None = None,
    symlink_member: bool = False,
) -> tuple[model_assets.ModelManifest, Path]:
    declared_content = declared_content if declared_content is not None else model_content
    manifest = write_test_manifest(tmp_path, declared={"layout": declared_content})
    data = json.loads(manifest.path.read_text(encoding="utf-8"))
    data["models"][0]["install_path"] = member_name
    manifest.path.write_text(json.dumps(data), encoding="utf-8")

    archive = tmp_path / "release.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
        info = zipfile.ZipInfo(member_name, date_time=(1980, 1, 1, 0, 0, 0))
        info.external_attr = (stat.S_IFREG | 0o644) << 16
        bundle.writestr(info, model_content)
        if extra_member is not None:
            extra = zipfile.ZipInfo(extra_member, date_time=(1980, 1, 1, 0, 0, 0))
            extra.filename = extra_member
            extra.external_attr = (
                (stat.S_IFLNK | 0o777) if symlink_member else (stat.S_IFREG | 0o644)
            ) << 16
            bundle.writestr(extra, b"extra")

    data = json.loads(manifest.path.read_text(encoding="utf-8"))
    data["release"]["size"] = archive.stat().st_size
    data["release"]["sha256"] = _sha256(archive.read_bytes())
    manifest.path.write_text(json.dumps(data), encoding="utf-8")
    return model_assets.load_manifest(manifest.path), archive


def test_default_manifest_uses_fixed_release_and_unique_paths():
    manifest = model_assets.load_manifest()

    assert manifest.release.tag == "models-v1"
    assert "latest" not in manifest.release.url.lower()
    assert len(manifest.models) == 7
    assert len({item.name for item in manifest.models}) == 7
    assert len({item.install_path for item in manifest.models}) == 7


def test_default_manifest_declares_bundled_license_files():
    manifest = model_assets.load_manifest()

    assert {item.name for item in manifest.release_files} == {
        "model_assets_notice",
        "agpl_3_0_license",
        "cc_by_nc_sa_4_0_license",
        "apache_2_0_license",
    }
    assert all(item.source_path for item in manifest.release_files)


def test_release_builder_bundles_and_installer_publishes_compliance_file(tmp_path):
    model_content = b"licensed-model"
    notice_content = b"model attribution and license notice\n"
    manifest = write_test_manifest(
        tmp_path,
        files={"layout": model_content},
        declared={"layout": model_content},
    )
    source_notice = manifest.repo_root / "models/release/MODEL-ASSETS-NOTICE.md"
    source_notice.parent.mkdir(parents=True)
    source_notice.write_bytes(notice_content)
    data = json.loads(manifest.path.read_text(encoding="utf-8"))
    data["release_files"] = [
        {
            "name": "model_assets_notice",
            "install_path": "models/runtime/licenses/MODEL-ASSETS-NOTICE.md",
            "source_path": "models/release/MODEL-ASSETS-NOTICE.md",
            "size": len(notice_content),
            "sha256": _sha256(notice_content),
            "source": "test notice",
            "version": "1",
            "license": "CC0-1.0",
        }
    ]
    data["release"]["unpacked_size"] += len(notice_content)
    manifest.path.write_text(json.dumps(data), encoding="utf-8")
    manifest = model_assets.load_manifest(manifest.path)
    archive = tmp_path / "licensed-release.zip"

    build = model_assets.build_release_archive(archive, manifest)
    data = json.loads(manifest.path.read_text(encoding="utf-8"))
    data["release"]["size"] = build["size"]
    data["release"]["sha256"] = build["sha256"]
    manifest.path.write_text(json.dumps(data), encoding="utf-8")
    manifest = model_assets.load_manifest(manifest.path)

    with zipfile.ZipFile(archive) as bundle:
        assert "models/runtime/licenses/MODEL-ASSETS-NOTICE.md" in bundle.namelist()
    result = model_assets.install_models(manifest, source_url=archive.as_uri())
    installed_notice = manifest.repo_root / "models/runtime/licenses/MODEL-ASSETS-NOTICE.md"
    assert result["available"] is True
    assert installed_notice.read_bytes() == notice_content


def test_manifest_rejects_parent_path(tmp_path):
    manifest = write_test_manifest(tmp_path)
    data = json.loads(manifest.path.read_text(encoding="utf-8"))
    data["models"][0]["install_path"] = "../outside.bin"
    manifest.path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(model_assets.ModelManifestError, match="install_path"):
        model_assets.load_manifest(manifest.path)


def test_verify_models_reports_missing_with_install_command(tmp_path):
    manifest = write_test_manifest(tmp_path)

    result = model_assets.verify_models(manifest)

    assert result["available"] is False
    assert result["models"][0]["status"] == "missing"
    assert "python -m pdf2md.models install" in result["error"]


def test_verify_models_accepts_matching_file(tmp_path):
    content = b"verified-layout"
    manifest = write_test_manifest(
        tmp_path,
        files={"layout": content},
        declared={"layout": content},
    )

    result = model_assets.verify_models(manifest)

    assert result["available"] is True
    assert result["models"][0]["status"] == "verified"


def test_verify_models_distinguishes_wrong_size_and_hash(tmp_path):
    expected = b"expected"
    wrong_size = write_test_manifest(
        tmp_path / "size",
        files={"layout": b"x"},
        declared={"layout": expected},
    )
    wrong_hash = write_test_manifest(
        tmp_path / "hash",
        files={"layout": b"wrong---"},
        declared={"layout": expected},
    )

    assert model_assets.verify_models(wrong_size)["models"][0]["status"] == "wrong_size"
    assert model_assets.verify_models(wrong_hash)["models"][0]["status"] == "wrong_hash"


def test_verify_models_recognizes_git_lfs_pointer(tmp_path):
    pointer = b"version https://git-lfs.github.com/spec/v1\noid sha256:" + b"0" * 64 + b"\nsize 10\n"
    manifest = write_test_manifest(
        tmp_path,
        files={"layout": pointer},
        declared={"layout": b"model-data"},
    )

    result = model_assets.verify_models(manifest)

    assert result["models"][0]["status"] == "git_lfs_pointer"


@pytest.mark.parametrize(
    "member",
    ["../escape.bin", "/absolute.bin", "C:/drive.bin"],
)
def test_install_rejects_unsafe_archive_members(tmp_path, member):
    manifest, archive = make_release(tmp_path, extra_member=member)

    with pytest.raises(model_assets.ModelInstallError, match="unsafe_archive"):
        model_assets.install_models(manifest, source_url=archive.as_uri())


def test_archive_name_validator_rejects_windows_separator():
    with pytest.raises(model_assets.ModelInstallError, match="unsafe_archive"):
        model_assets._safe_member_name("models\\escape.bin")


def test_install_rejects_undeclared_archive_member(tmp_path):
    manifest, archive = make_release(tmp_path, extra_member="models/runtime/extra.bin")

    with pytest.raises(model_assets.ModelInstallError, match="undeclared"):
        model_assets.install_models(manifest, source_url=archive.as_uri())


def test_install_rejects_symlink_member(tmp_path):
    manifest, archive = make_release(
        tmp_path,
        extra_member="models/runtime/link.bin",
        symlink_member=True,
    )

    with pytest.raises(model_assets.ModelInstallError, match="symlink"):
        model_assets.install_models(manifest, source_url=archive.as_uri())


def test_install_rejects_archive_digest_mismatch(tmp_path):
    manifest, archive = make_release(tmp_path)
    tampered = bytearray(archive.read_bytes())
    tampered[0] ^= 1
    archive.write_bytes(tampered)

    with pytest.raises(model_assets.ModelInstallError, match="archive_integrity"):
        model_assets.install_models(manifest, source_url=archive.as_uri())


def test_failed_install_preserves_existing_model(tmp_path):
    manifest, archive = make_release(
        tmp_path,
        model_content=b"corrupt-layout",
        declared_content=b"expected-layout",
    )
    target = model_assets.model_path("layout", manifest)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"previous-layout")

    with pytest.raises(model_assets.ModelInstallError, match="model_integrity"):
        model_assets.install_models(manifest, source_url=archive.as_uri())

    assert target.read_bytes() == b"previous-layout"


def test_install_publishes_verified_model(tmp_path):
    manifest, archive = make_release(tmp_path)

    result = model_assets.install_models(manifest, source_url=archive.as_uri())

    assert result["available"] is True
    assert model_assets.model_path("layout", manifest).read_bytes() == b"release-layout"


def test_release_builder_is_byte_deterministic(tmp_path):
    content = b"deterministic-layout"
    manifest = write_test_manifest(
        tmp_path,
        files={"layout": content},
        declared={"layout": content},
    )
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    first_result = model_assets.build_release_archive(first, manifest)
    second_result = model_assets.build_release_archive(second, manifest)

    assert first.read_bytes() == second.read_bytes()
    assert first_result["sha256"] == second_result["sha256"]
    assert first_result["models"] == ["layout"]


def test_status_cli_returns_nonzero_for_missing_models(tmp_path, capsys):
    manifest = write_test_manifest(tmp_path)

    code = model_assets.main(["status", "--manifest", str(manifest.path)])

    assert code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["available"] is False


def test_build_release_cli_writes_archive(tmp_path, capsys):
    content = b"cli-layout"
    manifest = write_test_manifest(
        tmp_path,
        files={"layout": content},
        declared={"layout": content},
    )
    output = tmp_path / "cli.zip"

    code = model_assets.main(
        ["build-release", "--manifest", str(manifest.path), "--output", str(output)]
    )

    assert code == 0
    assert output.is_file()
    assert json.loads(capsys.readouterr().out)["models"] == ["layout"]


def test_builder_can_use_legacy_source_without_changing_runtime_path(tmp_path, monkeypatch):
    content = b"legacy-layout"
    manifest = write_test_manifest(tmp_path, declared={"layout": content})
    legacy = tmp_path / "legacy" / "layout.pt"
    legacy.parent.mkdir()
    legacy.write_bytes(content)
    monkeypatch.setattr(model_assets, "_legacy_model_path", lambda name: legacy)
    output = tmp_path / "legacy.zip"

    result = model_assets.build_release_archive(output, manifest)

    assert result["models"] == ["layout"]
    assert not model_assets.model_path("layout", manifest).exists()
