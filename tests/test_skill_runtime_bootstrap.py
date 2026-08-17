import hashlib
import importlib.util
import io
import json
import sys
import zipfile
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
    helper.parent.mkdir(parents=True, exist_ok=True)
    helper.write_text("print('helper')\n", encoding="utf-8")
    return path


def _runtime_zip(*, unsafe: str | None = None) -> bytes:
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
    monkeypatch.setattr(
        launcher,
        "_script_path",
        lambda: skill / "scripts" / "yunshu_pdf.py",
    )

    assert launcher._find_existing_repo() == repo.resolve()


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


def test_dependency_file_uses_exact_lock_only_for_verified_platform(tmp_path):
    launcher = _load_launcher()

    assert launcher._dependency_file(
        tmp_path,
        system="Windows",
        machine="AMD64",
        version=(3, 13),
    ) == tmp_path / "requirements-lock.txt"
    assert launcher._dependency_file(
        tmp_path,
        system="Darwin",
        machine="arm64",
        version=(3, 13),
    ) == tmp_path / "requirements.txt"
    assert launcher._dependency_file(
        tmp_path,
        system="Linux",
        machine="x86_64",
        version=(3, 12),
    ) == tmp_path / "requirements.txt"


def test_completed_runtime_is_reused_without_download(monkeypatch, tmp_path):
    launcher = _load_launcher()
    paths = launcher._runtime_paths(tmp_path)
    _make_repo(paths.runtime)
    paths.python.parent.mkdir(parents=True)
    paths.python.write_text("python", encoding="utf-8")
    paths.state.parent.mkdir(parents=True)
    paths.state.write_text(
        json.dumps(
            {
                "runtime_version": launcher.RUNTIME_VERSION,
                "runtime_sha256": launcher.RUNTIME_SHA256,
                "model_sha256": launcher.MODEL_SHA256,
                "python": f"{sys.version_info.major}.{sys.version_info.minor}",
                "dependency_mode": launcher._dependency_mode(),
                "models_verified": True,
                "installed_at": 1.0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(launcher, "_cache_root", lambda: tmp_path)
    monkeypatch.setattr(
        launcher,
        "_download_verified",
        lambda *args, **kwargs: pytest.fail("completed runtime must remain offline"),
    )

    selected = launcher._ensure_managed_runtime()

    assert selected.repo == paths.runtime
    assert selected.python == paths.python


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
        (destination / "models").mkdir()
        (destination / "models" / "models.lock.json").write_text("{}", encoding="utf-8")
        (destination / "requirements.txt").write_text("requests>=2.28\n", encoding="utf-8")
        (destination / "requirements-lock.txt").write_text("requests==2.34.2\n", encoding="utf-8")

    class FakeBuilder:
        def __init__(self, **kwargs):
            pass

        def create(self, destination):
            python = Path(destination) / (
                "Scripts/python.exe" if launcher.platform.system() == "Windows" else "bin/python"
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
    assert any(command[-2:] == ["--source-url", launcher.MODEL_URL] for command in commands)
    assert any(command[-2:] == ["pdf2md.models", "verify"] for command in commands)


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
        lambda command, cwd: calls.append((command, cwd))
        or type("Result", (), {"returncode": 0})(),
    )
    monkeypatch.setattr(
        launcher.sys,
        "argv",
        ["yunshu_pdf.py", "render-page", "paper.pdf", "1"],
    )

    assert launcher.main() == 0
    assert calls[0][0][0] == sys.executable
    assert calls[0][0][1] == str(repo / "tools" / "pdf-reading" / "pdf2md.py")


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
        lambda command, cwd: calls.append((command, cwd))
        or type("Result", (), {"returncode": 0})(),
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
