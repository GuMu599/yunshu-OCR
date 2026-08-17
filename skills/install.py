#!/usr/bin/env python3
"""Install one Yunshu-OCR skill variant without replacing an existing skill."""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
DEFAULT_DESTINATIONS = {
    "codex": Path.home() / ".codex" / "skills" / "yunshu-ocr",
    "claude": Path.home() / ".claude" / "skills" / "yunshu-ocr",
    "universal": Path.home() / ".agents" / "skills" / "yunshu-ocr",
}
WORKBUDDY_VARIANT = "workbuddy"
WORKBUDDY_DEFAULT_ARTIFACT = ROOT / "dist" / "yunshu-ocr-workbuddy.zip"


def install_skill(
    variant: str,
    destination: str | Path | None = None,
    *,
    force: bool = False,
) -> Path:
    if variant not in DEFAULT_DESTINATIONS:
        raise ValueError(f"unknown skill variant: {variant}")
    source = SKILLS / variant / "yunshu-ocr"
    target = Path(destination).expanduser().resolve() if destination else DEFAULT_DESTINATIONS[variant]
    if target.exists() and any(target.iterdir()) and not force:
        raise FileExistsError(
            f"destination already contains a skill: {target}; choose another --dest or pass --force"
        )
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / "SKILL.md", target / "SKILL.md")
    scripts = target / "scripts"
    scripts.mkdir(exist_ok=True)
    shutil.copy2(SKILLS / "shared" / "yunshu_pdf.py", scripts / "yunshu_pdf.py")
    (target / ".yunshu-ocr-root").write_text(str(ROOT.resolve()), encoding="utf-8")
    return target


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
        archive.write(
            SKILLS / "shared" / "yunshu_pdf.py",
            "scripts/yunshu_pdf.py",
        )
        archive.writestr("references/yunshu-ocr-root.txt", str(ROOT.resolve()))
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("variant", choices=(*DEFAULT_DESTINATIONS, WORKBUDDY_VARIANT))
    parser.add_argument("--dest", type=Path, default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        if args.variant == WORKBUDDY_VARIANT:
            artifact = package_workbuddy(args.dest, force=args.force)
            print(json.dumps({
                "ok": True,
                "variant": args.variant,
                "artifact": str(artifact),
                "repository": str(ROOT.resolve()),
                "hint": (
                    "in WorkBuddy open Experts, Skills and Connectors > Add Skill > "
                    "Upload Skill, then select this ZIP"
                ),
            }, ensure_ascii=False))
            return 0
        destination = install_skill(args.variant, args.dest, force=args.force)
    except (FileExistsError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({
        "ok": True,
        "variant": args.variant,
        "destination": str(destination),
        "repository": str(ROOT.resolve()),
        "hint": "start a new Agent task so the installed skill is discovered",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
