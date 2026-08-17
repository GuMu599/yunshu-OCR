import hashlib
import importlib.util
import io
import json
import sys
import textwrap
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "skills" / "shared" / "yunshu_pdf.py"


class _VersionInfo(tuple):
    @property
    def major(self):
        return self[0]

    @property
    def minor(self):
        return self[1]


def _version(major, minor):
    return _VersionInfo((major, minor, 0, "final", 0))


def _load_launcher():
    spec = importlib.util.spec_from_file_location("yunshu_skill_launcher", LAUNCHER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _make_repo(path: Path) -> Path:
    helper = path / "tools" / "pdf-reading" / "pdf2md.py"
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text("print('helper')\n", encoding="utf-8")
    return path


def _write_model_inventory(launcher, repo: Path, payload: bytes = b"abc") -> Path:
    model = repo / "models" / "runtime" / "model.bin"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(payload)
    manifest = repo / "models" / "models.lock.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "install_path": "models/runtime/model.bin",
                        "size": len(payload),
                        "sha256": hashlib.sha256(payload).hexdigest(),
                    }
                ],
                "release_files": [],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    launcher.MODEL_MANIFEST_SHA256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
    return model


def _prepare_complete_runtime(launcher, paths) -> Path:
    _make_repo(paths.runtime)
    model = _write_model_inventory(launcher, paths.runtime)
    paths.python.parent.mkdir(parents=True, exist_ok=True)
    paths.python.write_text("python", encoding="utf-8")
    return model


def _runtime_zip(
    *,
    unsafe: str | None = None,
    extra_member: str | None = None,
    extra_members: tuple[str, ...] = (),
) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        if unsafe is not None:
            archive.writestr(unsafe, "escape")
        else:
            prefix = "yunshu-OCR-runtime-v1"
            archive.writestr(f"{prefix}/tools/pdf-reading/pdf2md.py", "print('ok')\n")
            archive.writestr(f"{prefix}/requirements.txt", "requests>=2.28\n")
            archive.writestr(f"{prefix}/requirements-lock.txt", "requests==2.34.2\n")
            archive.writestr(f"{prefix}/pdf2md/__init__.py", "")
            archive.writestr(f"{prefix}/models/models.lock.json", "{}")
            if extra_member is not None:
                archive.writestr(f"{prefix}/{extra_member}", "unexpected")
            for member in extra_members:
                archive.writestr(f"{prefix}/{member}", "unexpected")
    return stream.getvalue()


@pytest.mark.parametrize(
    ("system", "env", "home", "expected"),
    [
        (
            "Windows",
            {"LOCALAPPDATA": "C:/Cache"},
            "C:/Users/Test",
            Path("C:/Cache/yunshu-ocr"),
        ),
        (
            "Darwin",
            {},
            "/Users/test",
            Path("/Users/test/Library/Caches/yunshu-ocr"),
        ),
        (
            "Linux",
            {"XDG_CACHE_HOME": "/var/tmp/cache"},
            "/home/test",
            Path("/var/tmp/cache/yunshu-ocr"),
        ),
        (
            "Linux",
            {"XDG_CACHE_HOME": ""},
            "/home/test",
            Path("/home/test/.cache/yunshu-ocr"),
        ),
        (
            "Linux",
            {"XDG_CACHE_HOME": "relative/cache"},
            "/home/test",
            Path("/home/test/.cache/yunshu-ocr"),
        ),
        ("Linux", {}, "/home/test", Path("/home/test/.cache/yunshu-ocr")),
    ],
)
def test_cache_root_follows_platform_policy(system, env, home, expected):
    launcher = _load_launcher()

    assert launcher._cache_root(system=system, env=env, home=Path(home)) == expected


def test_runtime_paths_are_python_isolated_behind_one_cache_wide_lock(
    monkeypatch, tmp_path
):
    launcher = _load_launcher()
    monkeypatch.setattr(launcher.sys, "version_info", _version(3, 12))
    py312 = launcher._runtime_paths(tmp_path)
    monkeypatch.setattr(launcher.sys, "version_info", _version(3, 13))
    py313 = launcher._runtime_paths(tmp_path)

    assert py312.runtime != py313.runtime
    assert py312.venv != py313.venv
    assert py312.state != py313.state
    assert py312.lock == py313.lock


def test_python_version_cleanup_cannot_delete_another_runtime(monkeypatch, tmp_path):
    launcher = _load_launcher()
    monkeypatch.setattr(launcher.sys, "version_info", _version(3, 12))
    py312 = launcher._runtime_paths(tmp_path)
    py312.runtime.mkdir(parents=True)
    sentinel = py312.runtime / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    py312.venv.mkdir(parents=True)
    monkeypatch.setattr(launcher.sys, "version_info", _version(3, 13))
    monkeypatch.setattr(launcher, "_cache_root", lambda: tmp_path)

    def stop_after_cleanup(paths):
        assert sentinel.is_file()
        raise launcher.BootstrapError("stop", "test", "stop")

    monkeypatch.setattr(launcher, "_install_runtime", stop_after_cleanup)

    with pytest.raises(launcher.BootstrapError, match="stop"):
        launcher._ensure_managed_runtime()

    assert sentinel.is_file()


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
    monkeypatch.setattr(
        launcher,
        "_script_path",
        lambda: skill / "scripts" / "yunshu_pdf.py",
    )

    assert launcher._find_existing_repo() == repo.resolve()


@pytest.mark.parametrize("payload", [b"\xff\xfe", b"\x80not-utf8"])
def test_invalid_legacy_marker_encoding_is_ignored(monkeypatch, tmp_path, payload):
    launcher = _load_launcher()
    skill = tmp_path / "skill"
    marker = skill / "references" / "yunshu-ocr-root.txt"
    marker.parent.mkdir(parents=True)
    marker.write_bytes(payload)
    monkeypatch.delenv("YUNSHU_OCR_ROOT", raising=False)
    monkeypatch.setattr(
        launcher, "_script_path", lambda: skill / "scripts/yunshu_pdf.py"
    )

    assert launcher._find_existing_repo() is None


def test_unreadable_legacy_marker_is_ignored(monkeypatch, tmp_path):
    launcher = _load_launcher()
    skill = tmp_path / "skill"
    marker = skill / ".yunshu-ocr-root"
    marker.parent.mkdir(parents=True)
    marker.write_text("ignored", encoding="utf-8")
    original_read_text = launcher.Path.read_text

    def fail_marker_read(path, *args, **kwargs):
        if path == marker:
            raise OSError("marker denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.delenv("YUNSHU_OCR_ROOT", raising=False)
    monkeypatch.setattr(
        launcher, "_script_path", lambda: skill / "scripts/yunshu_pdf.py"
    )
    monkeypatch.setattr(launcher.Path, "read_text", fail_marker_read)

    assert launcher._find_existing_repo() is None


def test_release_constants_match_published_assets():
    launcher = _load_launcher()

    assert launcher.RUNTIME_VERSION == "runtime-v1"
    assert launcher.RUNTIME_URL == (
        "https://github.com/GuMu599/yunshu-OCR/releases/download/"
        "runtime-v1/yunshu-ocr-runtime-v1.zip"
    )
    assert launcher.RUNTIME_SIZE == 349674
    assert launcher.RUNTIME_SHA256 == (
        "f4f95dbc12ffd060ce662ca1dbc59f2d5b867ccd703183f5f829502e96f84030"
    )
    assert launcher.MODEL_URL == (
        "https://github.com/GuMu599/yunshu-OCR/releases/download/"
        "models-v1/pdf2md-models-v1.zip"
    )
    assert launcher.MODEL_SIZE == 185346805
    assert launcher.MODEL_SHA256 == (
        "daa85d380551a93f0464950181c3bc29ab16525a55b3a6664108183aa49c9fb0"
    )
    assert (
        launcher.MODEL_MANIFEST_SHA256
        == "6b5b93e645ab682546001000341cc91a3893fad68dd42732c21899c746b393a3"
    )


def test_download_rejects_wrong_hash(monkeypatch, tmp_path):
    launcher = _load_launcher()
    payload = b"not-the-release"

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        launcher.urllib.request,
        "urlopen",
        lambda request, timeout: Response(payload),
    )

    with pytest.raises(launcher.BootstrapError) as raised:
        launcher._download_verified(
            "https://example.invalid/runtime.zip",
            tmp_path / "runtime.zip",
            len(payload),
            "0" * 64,
        )

    assert raised.value.code == "archive_integrity"
    assert not (tmp_path / "runtime.zip").exists()


def test_download_reuses_an_existing_verified_archive(monkeypatch, tmp_path):
    launcher = _load_launcher()
    payload = b"verified"
    destination = tmp_path / "runtime.zip"
    destination.write_bytes(payload)
    monkeypatch.setattr(
        launcher.urllib.request,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("verified archive must be reused offline"),
    )

    result = launcher._download_verified(
        "https://example.invalid/runtime.zip",
        destination,
        len(payload),
        hashlib.sha256(payload).hexdigest(),
    )

    assert result == destination


def test_safe_extract_strips_single_release_prefix(tmp_path):
    launcher = _load_launcher()
    archive = tmp_path / "runtime.zip"
    archive.write_bytes(_runtime_zip())
    target = tmp_path / "runtime"

    launcher._extract_runtime(archive, target)

    assert (target / "tools" / "pdf-reading" / "pdf2md.py").is_file()
    assert (target / "requirements.txt").is_file()


@pytest.mark.parametrize("member", ["../escape.txt", "/absolute.txt", "C:/escape.txt"])
def test_safe_extract_rejects_unsafe_members(tmp_path, member):
    launcher = _load_launcher()
    archive = tmp_path / "unsafe.zip"
    archive.write_bytes(_runtime_zip(unsafe=member))

    with pytest.raises(launcher.BootstrapError) as raised:
        launcher._extract_runtime(archive, tmp_path / "runtime")

    assert raised.value.code == "archive_unsafe"
    assert not (tmp_path / "escape.txt").exists()


def test_safe_extract_rejects_undeclared_runtime_members(tmp_path):
    launcher = _load_launcher()
    archive = tmp_path / "unexpected.zip"
    archive.write_bytes(_runtime_zip(extra_member="unexpected/payload.exe"))

    with pytest.raises(launcher.BootstrapError) as raised:
        launcher._extract_runtime(archive, tmp_path / "runtime")

    assert raised.value.code == "archive_unsafe"
    assert "undeclared" in str(raised.value)


@pytest.mark.parametrize(
    "members",
    [
        ("models/production/model.bin", "models/production/model.bin"),
        ("models/production/model.bin", "models/production/MODEL.bin"),
    ],
)
def test_safe_extract_rejects_duplicate_or_case_colliding_members(tmp_path, members):
    launcher = _load_launcher()
    if members[0] == members[1]:
        with pytest.warns(UserWarning, match="Duplicate name"):
            payload = _runtime_zip(extra_members=members)
    else:
        payload = _runtime_zip(extra_members=members)
    archive = tmp_path / "collision.zip"
    archive.write_bytes(payload)
    with pytest.raises(launcher.BootstrapError) as raised:
        launcher._extract_runtime(archive, tmp_path / "runtime")
    assert raised.value.code == "archive_unsafe"
    assert "duplicate" in str(raised.value).lower()


def test_dependency_file_uses_exact_lock_only_for_verified_platform(tmp_path):
    launcher = _load_launcher()

    assert (
        launcher._dependency_file(
            tmp_path,
            system="Windows",
            machine="AMD64",
            version=(3, 13),
        )
        == tmp_path / "requirements-lock.txt"
    )
    assert (
        launcher._dependency_file(
            tmp_path,
            system="Darwin",
            machine="arm64",
            version=(3, 13),
        )
        == tmp_path / "requirements.txt"
    )


def test_models_present_rejects_a_fabricated_manifest(tmp_path):
    launcher = _load_launcher()
    repo = _make_repo(tmp_path / "runtime")
    model = repo / "models/runtime/model.bin"
    model.parent.mkdir(parents=True)
    model.write_bytes(b"fabricated")
    manifest = repo / "models/models.lock.json"
    manifest.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "install_path": "models/runtime/model.bin",
                        "size": model.stat().st_size,
                        "sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
                    }
                ],
                "release_files": [],
            }
        ),
        encoding="utf-8",
    )
    assert launcher._models_present(repo) is False


def test_cached_state_does_not_rehash_unchanged_large_models(monkeypatch, tmp_path):
    launcher = _load_launcher()
    paths = launcher._runtime_paths(tmp_path)
    model = _prepare_complete_runtime(launcher, paths)
    launcher._write_state(paths)
    original = launcher._file_sha256

    def guarded(path):
        if path == model:
            pytest.fail("unchanged cached model must not be rehashed")
        return original(path)

    monkeypatch.setattr(launcher, "_file_sha256", guarded)
    monkeypatch.setattr(launcher, "_cache_root", lambda: tmp_path)
    assert launcher._ensure_managed_runtime() == launcher.RuntimeSelection(
        paths.runtime, paths.python, paths.log
    )


def test_changed_model_metadata_triggers_full_verification_and_state_refresh(
    monkeypatch, tmp_path
):
    launcher = _load_launcher()
    paths = launcher._runtime_paths(tmp_path)
    model = _prepare_complete_runtime(launcher, paths)
    launcher._write_state(paths)
    before = json.loads(paths.state.read_text(encoding="utf-8"))[
        "model_metadata_fingerprint"
    ]
    metadata = model.stat()
    launcher.os.utime(
        model, ns=(metadata.st_atime_ns, metadata.st_mtime_ns + 1_000_000_000)
    )
    original, hashed = launcher._file_sha256, []

    def recording(path):
        if path == model:
            hashed.append(path)
        return original(path)

    monkeypatch.setattr(launcher, "_file_sha256", recording)
    monkeypatch.setattr(launcher, "_cache_root", lambda: tmp_path)
    monkeypatch.setattr(
        launcher,
        "_download_verified",
        lambda *a, **k: pytest.fail("verified cache must recover offline"),
    )
    selected = launcher._ensure_managed_runtime()
    after = json.loads(paths.state.read_text(encoding="utf-8"))[
        "model_metadata_fingerprint"
    ]
    assert selected == launcher.RuntimeSelection(paths.runtime, paths.python, paths.log)
    assert hashed == [model]
    assert after != before


def test_interruption_after_runtime_publish_recovers_staged_venv_offline(
    monkeypatch, tmp_path
):
    launcher = _load_launcher()
    paths = launcher._runtime_paths(tmp_path)
    _make_repo(paths.runtime)
    _write_model_inventory(launcher, paths.runtime)
    stage = tmp_path / f"{paths.stage_prefix}interrupted"
    staged_python = stage / "venv" / paths.python.relative_to(paths.venv)
    staged_python.parent.mkdir(parents=True)
    staged_python.write_text("python", encoding="utf-8")
    launcher._write_publish_journal(paths, stage)
    monkeypatch.setattr(launcher, "_cache_root", lambda: tmp_path)
    monkeypatch.setattr(
        launcher,
        "_download_verified",
        lambda *a, **k: pytest.fail("published cache must recover offline"),
    )
    assert launcher._ensure_managed_runtime() == launcher.RuntimeSelection(
        paths.runtime, paths.python, paths.log
    )
    assert paths.state.is_file() and not paths.journal.exists()


def test_interruption_after_venv_publish_reconstructs_state_offline(
    monkeypatch, tmp_path
):
    launcher = _load_launcher()
    paths = launcher._runtime_paths(tmp_path)
    _prepare_complete_runtime(launcher, paths)
    stage = tmp_path / f"{paths.stage_prefix}interrupted"
    stage.mkdir()
    launcher._write_publish_journal(paths, stage)
    monkeypatch.setattr(launcher, "_cache_root", lambda: tmp_path)
    monkeypatch.setattr(
        launcher,
        "_download_verified",
        lambda *a, **k: pytest.fail("published cache must recover offline"),
    )
    assert launcher._ensure_managed_runtime() == launcher.RuntimeSelection(
        paths.runtime, paths.python, paths.log
    )
    assert paths.state.is_file() and not paths.journal.exists()
    assert (
        launcher._dependency_file(
            tmp_path,
            system="Linux",
            machine="x86_64",
            version=(3, 12),
        )
        == tmp_path / "requirements.txt"
    )


def test_completed_runtime_is_reused_without_download(monkeypatch, tmp_path):
    launcher = _load_launcher()
    paths = launcher._runtime_paths(tmp_path)
    _prepare_complete_runtime(launcher, paths)
    launcher._write_state(paths)
    monkeypatch.setattr(launcher, "_cache_root", lambda: tmp_path)
    monkeypatch.setattr(
        launcher,
        "_download_verified",
        lambda *args, **kwargs: pytest.fail("completed runtime must remain offline"),
    )

    selected = launcher._ensure_managed_runtime()

    assert selected.repo == paths.runtime
    assert selected.python == paths.python


def test_state_is_invalid_when_a_declared_model_is_missing(tmp_path):
    launcher = _load_launcher()
    paths = launcher._runtime_paths(tmp_path)
    model = _prepare_complete_runtime(launcher, paths)
    launcher._write_state(paths)
    model.unlink()

    assert launcher._state_valid(paths) is False
    assert launcher._reconstruct_state(paths) is False


def test_state_is_invalid_when_a_declared_model_hash_mismatches(tmp_path):
    launcher = _load_launcher()
    paths = launcher._runtime_paths(tmp_path)
    model = _prepare_complete_runtime(launcher, paths)
    launcher._write_state(paths)
    model.write_bytes(b"bad")

    assert launcher._state_valid(paths) is False
    assert launcher._reconstruct_state(paths) is False


def test_failed_install_does_not_publish_completion_state(monkeypatch, tmp_path):
    launcher = _load_launcher()
    monkeypatch.setattr(launcher, "_cache_root", lambda: tmp_path)
    monkeypatch.setattr(
        launcher,
        "_download_verified",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            launcher.BootstrapError("download_failed", "download", "offline")
        ),
    )

    with pytest.raises(launcher.BootstrapError):
        launcher._ensure_managed_runtime()

    assert not launcher._runtime_paths(tmp_path).state.exists()


def test_install_lock_reports_contention_without_deleting_the_lock_path(tmp_path):
    launcher = _load_launcher()
    lock = tmp_path / "state" / "runtime.lock"
    ownership = launcher._acquire_lock(lock, timeout=0.1)
    try:
        with pytest.raises(launcher.BootstrapError) as raised:
            launcher._acquire_lock(lock, timeout=0.0)
        assert raised.value.code == "install_busy"
        assert lock.is_file()
    finally:
        launcher._release_lock(ownership)


def test_install_lock_is_released_when_holder_process_exits(tmp_path):
    launcher = _load_launcher()
    lock = tmp_path / "state/runtime.lock"
    code = textwrap.dedent(
        """
        import importlib.util, os, pathlib, sys
        spec = importlib.util.spec_from_file_location("child_launcher", sys.argv[1])
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        module._acquire_lock(pathlib.Path(sys.argv[2]), timeout=1.0)
        os._exit(0)
        """
    )
    completed = launcher.subprocess.run(
        [sys.executable, "-c", code, str(LAUNCHER), str(lock)],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0

    ownership = launcher._acquire_lock(lock, timeout=0.5)
    launcher._release_lock(ownership)
    assert lock.is_file()


def test_releasing_an_old_handle_never_deletes_replacement_lock_content(tmp_path):
    launcher = _load_launcher()
    lock = tmp_path / "state/runtime.lock"
    ownership = launcher._acquire_lock(lock, timeout=0.1)
    launcher._release_lock(ownership)
    lock.write_text("replacement", encoding="utf-8")

    launcher._release_lock(ownership)

    assert lock.read_text(encoding="utf-8") == "replacement"


def test_cleanup_staging_removes_only_current_python_stages(tmp_path):
    launcher = _load_launcher()
    paths = launcher._runtime_paths(tmp_path)
    stale = tmp_path / f"{paths.stage_prefix}stale"
    other_python = tmp_path / ".bootstrap-py999-stale"
    keep = tmp_path / "runtime"
    stale.mkdir()
    other_python.mkdir()
    keep.mkdir()

    launcher._cleanup_staging(paths)

    assert not stale.exists()
    assert other_python.exists()
    assert keep.exists()


def test_install_runtime_runs_dependency_and_model_verification(monkeypatch, tmp_path):
    launcher = _load_launcher()
    paths = launcher._runtime_paths(tmp_path)
    commands = []

    def fake_download(url, destination, size, sha256):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"runtime")
        return destination

    def fake_extract(archive, destination):
        _make_repo(destination)
        (destination / "pdf2md").mkdir()
        (destination / "pdf2md" / "__init__.py").write_text("", encoding="utf-8")
        _write_model_inventory(launcher, destination)
        (destination / "requirements.txt").write_text(
            "requests>=2.28\n", encoding="utf-8"
        )
        (destination / "requirements-lock.txt").write_text(
            "requests==2.34.2\n", encoding="utf-8"
        )

    class FakeBuilder:
        def __init__(self, **kwargs):
            pass

        def create(self, destination):
            python = Path(destination) / (
                "Scripts/python.exe"
                if launcher.platform.system() == "Windows"
                else "bin/python"
            )
            python.parent.mkdir(parents=True)
            python.write_text("python", encoding="utf-8")

    monkeypatch.setattr(launcher, "_download_verified", fake_download)
    monkeypatch.setattr(launcher, "_extract_runtime", fake_extract)
    monkeypatch.setattr(launcher.venv, "EnvBuilder", FakeBuilder)
    monkeypatch.setattr(
        launcher,
        "_run_logged",
        lambda command, **kwargs: commands.append(command),
    )

    launcher._install_runtime(paths)

    assert paths.state.is_file()
    assert paths.python.is_file()
    assert any(
        command[-2:] == ["--source-url", launcher.MODEL_URL] for command in commands
    )
    assert any(command[-2:] == ["pdf2md.models", "verify"] for command in commands)


def test_real_runtime_publish_failure_preserves_staged_venv_for_offline_recovery(
    monkeypatch, tmp_path
):
    launcher = _load_launcher()
    paths = launcher._runtime_paths(tmp_path)

    def fake_download(url, destination, size, sha256):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"runtime")
        return destination

    def fake_extract(archive, destination):
        _make_repo(destination)
        (destination / "pdf2md").mkdir()
        (destination / "pdf2md/__init__.py").write_text("", encoding="utf-8")
        _write_model_inventory(launcher, destination)
        (destination / "requirements.txt").write_text(
            "requests>=2.28\n", encoding="utf-8"
        )
        (destination / "requirements-lock.txt").write_text(
            "requests==2.34.2\n", encoding="utf-8"
        )

    class FakeBuilder:
        def __init__(self, **kwargs):
            pass

        def create(self, destination):
            python = Path(destination) / (
                "Scripts/python.exe"
                if launcher.platform.system() == "Windows"
                else "bin/python"
            )
            python.parent.mkdir(parents=True)
            python.write_text("python", encoding="utf-8")

    monkeypatch.setattr(launcher, "_download_verified", fake_download)
    monkeypatch.setattr(launcher, "_extract_runtime", fake_extract)
    monkeypatch.setattr(launcher.venv, "EnvBuilder", FakeBuilder)
    monkeypatch.setattr(launcher, "_run_logged", lambda *args, **kwargs: None)
    original_replace = launcher.os.replace

    def fail_venv_publish(source, destination):
        if Path(source).name == "venv" and Path(destination) == paths.venv:
            raise OSError("publish interrupted")
        return original_replace(source, destination)

    monkeypatch.setattr(launcher.os, "replace", fail_venv_publish)

    with pytest.raises(launcher.BootstrapError) as raised:
        launcher._install_runtime(paths)

    assert raised.value.stage == "publish"
    stage = launcher._read_publish_journal(paths)
    assert stage is not None
    staged_python = stage / "venv" / paths.python.relative_to(paths.venv)
    assert paths.runtime.is_dir()
    assert staged_python.is_file()

    monkeypatch.setattr(launcher.os, "replace", original_replace)
    monkeypatch.setattr(launcher, "_cache_root", lambda: tmp_path)
    monkeypatch.setattr(
        launcher,
        "_install_runtime",
        lambda *args, **kwargs: pytest.fail("recovery must remain offline"),
    )

    selected = launcher._ensure_managed_runtime()

    assert selected.repo == paths.runtime
    assert selected.python == paths.python


def test_logged_subprocess_oserror_keeps_stage_and_log(monkeypatch, tmp_path):
    launcher = _load_launcher()
    log = tmp_path / "logs/bootstrap.log"
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(OSError("spawn denied")),
    )
    with pytest.raises(launcher.BootstrapError) as raised:
        launcher._run_logged(
            ["python", "-m", "pip", "install"],
            cwd=tmp_path,
            log=log,
            code="dependency_failed",
            stage="dependencies",
        )
    assert (raised.value.code, raised.value.stage, raised.value.log) == (
        "dependency_failed",
        "dependencies",
        log,
    )


def test_main_uses_existing_repo_without_bootstrap(monkeypatch, tmp_path):
    launcher = _load_launcher()
    repo = _make_repo(tmp_path / "repo")
    calls = []
    monkeypatch.setattr(launcher, "_find_existing_repo", lambda: repo)
    monkeypatch.setattr(
        launcher,
        "_ensure_managed_runtime",
        lambda: pytest.fail("existing repo must win"),
    )
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda command, cwd: (
            calls.append((command, cwd)) or type("Result", (), {"returncode": 0})()
        ),
    )
    monkeypatch.setattr(
        launcher.sys,
        "argv",
        ["yunshu_pdf.py", "render-page", "paper.pdf", "1"],
    )

    assert launcher.main() == 0
    assert calls[0][0][0] == sys.executable
    assert calls[0][0][1] == str(repo / "tools" / "pdf-reading" / "pdf2md.py")


def test_python_version_is_checked_before_existing_repo_resolution(monkeypatch):
    launcher = _load_launcher()
    monkeypatch.setattr(launcher.sys, "version_info", (3, 9, 9))
    monkeypatch.setattr(
        launcher,
        "_find_existing_repo",
        lambda: pytest.fail(
            "unsupported Python must fail before repository resolution"
        ),
    )

    with pytest.raises(launcher.BootstrapError) as raised:
        launcher._select_runtime()

    assert raised.value.code == "python_unsupported"
    assert raised.value.stage == "preflight"


def test_main_uses_managed_python_when_repo_is_absent(monkeypatch, tmp_path):
    launcher = _load_launcher()
    repo = _make_repo(tmp_path / "runtime")
    python = tmp_path / "venv" / "python"
    calls = []
    monkeypatch.setattr(launcher, "_find_existing_repo", lambda: None)
    monkeypatch.setattr(
        launcher,
        "_ensure_managed_runtime",
        lambda: launcher.RuntimeSelection(repo, python),
    )
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda command, cwd: (
            calls.append((command, cwd)) or type("Result", (), {"returncode": 0})()
        ),
    )
    monkeypatch.setattr(
        launcher.sys,
        "argv",
        ["yunshu_pdf.py", "ensure", "paper.pdf"],
    )

    assert launcher.main() == 0
    assert calls[0][0][0] == str(python)


def test_main_prints_machine_readable_bootstrap_error(monkeypatch, capsys):
    launcher = _load_launcher()
    monkeypatch.setattr(launcher, "_find_existing_repo", lambda: None)
    monkeypatch.setattr(
        launcher,
        "_ensure_managed_runtime",
        lambda: (_ for _ in ()).throw(
            launcher.BootstrapError("download_failed", "download", "offline")
        ),
    )

    assert launcher.main() == 2

    payload = json.loads(capsys.readouterr().err)
    assert payload == {
        "ok": False,
        "error": "download_failed",
        "stage": "download",
        "message": "offline",
    }


def test_main_reports_helper_spawn_oserror_with_dispatch_stage_and_log(
    monkeypatch, tmp_path, capsys
):
    launcher = _load_launcher()
    repo = _make_repo(tmp_path / "runtime")
    python, log = tmp_path / "venv/python", tmp_path / "logs/bootstrap.log"
    monkeypatch.setattr(
        launcher,
        "_select_runtime",
        lambda: launcher.RuntimeSelection(repo, python, log),
    )
    monkeypatch.setattr(
        launcher.subprocess,
        "run",
        lambda *a, **k: (_ for _ in ()).throw(OSError("helper missing")),
    )
    assert launcher.main() == 2
    assert json.loads(capsys.readouterr().err) == {
        "ok": False,
        "error": "helper_failed",
        "stage": "dispatch",
        "message": "helper missing",
        "log": str(log),
    }


def test_main_reports_cache_write_errors_as_machine_readable_json(
    monkeypatch,
    tmp_path,
    capsys,
):
    launcher = _load_launcher()
    (tmp_path / "state").write_text("not a directory", encoding="utf-8")
    monkeypatch.setattr(launcher, "_find_existing_repo", lambda: None)
    monkeypatch.setattr(launcher, "_cache_root", lambda: tmp_path)

    assert launcher.main() == 2

    payload = json.loads(capsys.readouterr().err)
    assert payload["ok"] is False
    assert payload["error"] == "cache_unavailable"
    assert payload["stage"] == "cache"
