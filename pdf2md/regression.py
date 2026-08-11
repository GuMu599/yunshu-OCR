"""Manifest-driven real-document regression runner.

Large/copyrighted PDFs stay outside Git. The committed manifest stores paths or
environment-variable references plus structural expectations.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path


def _ordered_text(report: dict) -> str:
    chunks = []
    for page in report.get("elements", []):
        for item in sorted(page.get("items", []), key=lambda it: it.get("reading_order", 0)):
            chunks.append(str(item.get("text") or item.get("markdown") or ""))
    return "\n".join(chunks)


def _match_key(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(text or ""))
    normalized = re.sub(r"(?i)\bfig[^0-9A-Za-z\u4e00-\u9fff]{0,4}(?=\d)", "fig", normalized)
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", normalized).lower()


def evaluate_report(report: dict, expected: dict) -> dict:
    failures: list[str] = []
    stats = report.get("stats", {})
    quality = report.get("quality", {})
    for field in ("title", "authors"):
        if field in expected and report.get("meta", {}).get(field) != expected[field]:
            failures.append(
                f"{field}: expected {expected[field]!r}, got {report.get('meta', {}).get(field)!r}"
            )
    for field in ("images", "tables", "formulas"):
        if field in expected and stats.get(field) != expected[field]:
            failures.append(f"{field}: expected {expected[field]}, got {stats.get(field)}")
    if "formulas_min" in expected and stats.get("formulas", 0) < expected["formulas_min"]:
        failures.append(
            f"formulas_min: expected >= {expected['formulas_min']}, got {stats.get('formulas', 0)}"
        )
    if (
        "inline_formulas_min" in expected
        and stats.get("inline_formulas", 0) < expected["inline_formulas_min"]
    ):
        failures.append(
            "inline_formulas_min: expected >= "
            f"{expected['inline_formulas_min']}, got {stats.get('inline_formulas', 0)}"
        )
    if (
        "formula_fallback_images_max" in expected
        and stats.get("formula_fallback_images", 0) > expected["formula_fallback_images_max"]
    ):
        failures.append(
            "formula_fallback_images_max: expected <= "
            f"{expected['formula_fallback_images_max']}, "
            f"got {stats.get('formula_fallback_images', 0)}"
        )
    if "formula_text_duplicates_remaining_max" in expected:
        actual = stats.get("formula_text_duplicates_remaining")
        if actual is None:
            failures.append("formula_text_duplicates_remaining: missing")
        elif actual > expected["formula_text_duplicates_remaining_max"]:
            failures.append(
                "formula_text_duplicates_remaining: expected <= "
                f"{expected['formula_text_duplicates_remaining_max']}, got {actual}"
            )
    if quality.get("duplicate_text_count", 0) > expected.get("duplicate_text_max", float("inf")):
        failures.append(f"duplicate_text_count: got {quality.get('duplicate_text_count')}")

    present_types = {
        item.get("type") for page in report.get("elements", []) for item in page.get("items", [])
    }
    for forbidden in expected.get("forbidden_types", []):
        if forbidden in present_types:
            failures.append(f"forbidden type present: {forbidden}")

    ordered = _match_key(_ordered_text(report))
    for before, after in expected.get("order", []):
        before_key, after_key = _match_key(before), _match_key(after)
        before_at, after_at = ordered.find(before_key), ordered.find(after_key)
        if before_at < 0 or after_at < 0 or before_at >= after_at:
            failures.append(f"order: expected {before!r} before {after!r}")
    return {"passed": not failures, "failures": failures}


def _resolve_pdf(record: dict) -> Path:
    if record.get("pdf_env"):
        value = os.environ.get(record["pdf_env"])
        if not value:
            raise RuntimeError(f"missing environment variable: {record['pdf_env']}")
        return Path(value).expanduser().resolve()
    return Path(record["pdf"]).expanduser().resolve()


def load_manifest(path: str | os.PathLike) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real-PDF structural regression cases")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", default=None, help="JSON result path")
    parser.add_argument("--layout-model", default=None)
    parser.add_argument(
        "--layout-model-sha256",
        default=None,
        help="Pinned SHA-256 for a custom executable .pt layout model",
    )
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()

    from .pipeline import convert_pdf

    results = []
    with tempfile.TemporaryDirectory(prefix="pdf2md-regression-") as temp:
        for record in load_manifest(args.manifest):
            name = record["name"]
            try:
                pdf = _resolve_pdf(record)
                if not pdf.is_file():
                    raise RuntimeError(f"PDF not found: {pdf}")
                report = convert_pdf(
                    str(pdf), str(Path(temp) / name),
                    layout_model_path=args.layout_model,
                    layout_model_sha256=args.layout_model_sha256,
                    offline=args.offline, use_table_model=record.get("use_table_model", True),
                )
                evaluation = evaluate_report(report, record.get("expected", {}))
                results.append({"name": name, **evaluation})
            except Exception as exc:  # noqa: BLE001
                results.append({"name": name, "passed": False, "failures": [str(exc)]})

    payload = {"passed": all(result["passed"] for result in results), "cases": results}
    if args.out:
        Path(args.out).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for result in results:
        mark = "PASS" if result["passed"] else "FAIL"
        print(f"{mark} {result['name']}")
        for failure in result["failures"]:
            print(f"  - {failure}")
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
