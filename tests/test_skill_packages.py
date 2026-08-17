import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
VARIANTS = ("codex", "claude", "workbuddy", "universal")


def _load_installer():
    path = ROOT / "skills" / "install.py"
    spec = importlib.util.spec_from_file_location("yunshu_skill_installer", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_four_skill_variants_share_the_pdf_binding_and_fallback_contract():
    for variant in VARIANTS:
        skill = ROOT / "skills" / variant / "yunshu-ocr" / "SKILL.md"
        text = skill.read_text(encoding="utf-8")
        assert "name: yunshu-ocr" in text
        assert "Use when" in text
        assert "ensure" in text
        assert "locate" in text
        assert "render-page" in text
        assert "Markdown" in text
        assert "PDF 文件页" in text
        assert "PDF 原始" in text


def test_readme_routes_each_agent_to_the_correct_download():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "skills/codex/yunshu-ocr" in readme
    assert "skills/claude/yunshu-ocr" in readme
    assert "skills/workbuddy/yunshu-ocr" in readme
    assert "skills/universal/yunshu-ocr" in readme
    assert "python skills/install.py codex" in readme
    assert "python skills/install.py claude" in readme
    assert "python skills/install.py workbuddy" in readme
    assert "python skills/install.py universal" in readme


def test_installer_copies_selected_skill_and_records_repository_root(tmp_path):
    installer = _load_installer()
    destination = tmp_path / "installed" / "yunshu-ocr"

    result = installer.install_skill("codex", destination=destination)

    assert result == destination
    assert (destination / "SKILL.md").exists()
    assert (destination / "scripts" / "yunshu_pdf.py").exists()
    recorded = (destination / ".yunshu-ocr-root").read_text(encoding="utf-8").strip()
    assert Path(recorded).resolve() == ROOT.resolve()


def test_variant_descriptions_are_platform_specific():
    texts = {
        variant: (ROOT / "skills" / variant / "yunshu-ocr" / "SKILL.md").read_text(encoding="utf-8")
        for variant in VARIANTS
    }
    assert "Codex" in texts["codex"]
    assert "Claude Code" in texts["claude"]
    assert "WorkBuddy" in texts["workbuddy"]
    assert "Agent Skills" in texts["universal"]


def test_each_source_variant_is_directly_downloadable_with_its_launcher():
    shared = (ROOT / "skills" / "shared" / "yunshu_pdf.py").read_text(encoding="utf-8")
    for variant in VARIANTS:
        launcher = ROOT / "skills" / variant / "yunshu-ocr" / "scripts" / "yunshu_pdf.py"
        assert launcher.read_text(encoding="utf-8").rstrip("\n") == shared.rstrip("\n")


def test_workbuddy_manifest_has_minimum_enterprise_metadata():
    text = (ROOT / "skills" / "workbuddy" / "yunshu-ocr" / "manifest.yaml").read_text(
        encoding="utf-8"
    )
    assert "name: yunshu-ocr" in text
    assert "version: 1.0.0" in text
    assert "category: document-processing" in text
    assert "author: GuMu599" in text


def test_workbuddy_metadata_explains_the_zero_token_scope_without_overclaiming():
    skill = (ROOT / "skills" / "workbuddy" / "yunshu-ocr" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    manifest = (
        ROOT / "skills" / "workbuddy" / "yunshu-ocr" / "manifest.yaml"
    ).read_text(encoding="utf-8")

    assert "PDF 转换、OCR、Markdown 生成和页码渲染" in skill
    assert "不消耗 LLM Token" in skill
    assert "WorkBuddy 后续阅读与回答仍可能消耗平台额度" in skill
    assert "不消耗 LLM Token" in manifest


def test_workbuddy_packager_creates_portable_upload_zip(tmp_path):
    installer = _load_installer()
    artifact = installer.package_workbuddy(tmp_path / "yunshu-ocr-workbuddy.zip")

    assert artifact == (tmp_path / "yunshu-ocr-workbuddy.zip").resolve()
    with zipfile.ZipFile(artifact) as archive:
        assert archive.namelist() == [
            "SKILL.md",
            "manifest.yaml",
            "scripts/yunshu_pdf.py",
        ]
        assert all(
            not any(part.startswith(".") for part in Path(name).parts)
            for name in archive.namelist()
        )
        decoded_text = "\n".join(
            archive.read(name).decode("utf-8") for name in archive.namelist()
        )
        assert str(ROOT.resolve()) not in decoded_text
        assert r"E:\Codex" not in decoded_text
        assert r"C:\Users\GuMu" not in decoded_text


def test_workbuddy_cli_omits_repository_and_keeps_upload_hint(monkeypatch, tmp_path, capsys):
    installer = _load_installer()
    artifact = tmp_path / "yunshu-ocr-workbuddy.zip"
    monkeypatch.setattr(
        sys,
        "argv",
        ["install.py", "workbuddy", "--dest", str(artifact)],
    )

    assert installer.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["artifact"] == str(artifact.resolve())
    assert "repository" not in payload
    assert "Upload Skill" in payload["hint"]


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


def test_readmes_describe_portable_first_use_and_offline_reuse():
    for filename in ("README.md", "AI_README.md"):
        text = (ROOT / filename).read_text(encoding="utf-8")
        assert "首次使用" in text
        assert "185 MB" in text
        assert "离线" in text
        assert "YUNSHU_OCR_ROOT" in text
        assert "ZIP 内记录生成时的仓库绝对路径" not in text
        assert "重新上传" not in text
