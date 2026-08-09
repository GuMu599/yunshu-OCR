"""表格识别基准: manifest 驱动, 输出 recall / structure TEDS / cell CER / 质量门控准确率.

用法:
    python -m pdf2md.benchmark --manifest tests/benchmarks/tables/manifest.jsonl \
        --out benchmark_report.json [--dpi 300] [--no-model] [--level table|pipeline]

--level table (默认): 直接调 tables.recognize_table, 确定性、不依赖 YOLO。
--level pipeline: 全链路 convert_pdf, 检查表格 item 与 bbox 重叠 (Phase 3 用)。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz  # noqa: E402

from pdf2md.geometry import intersect_area
from pdf2md.teds import cell_cer, teds  # noqa: E402

_REPO = Path(__file__).resolve().parent.parent


def load_manifest(path) -> list[dict]:
    recs = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            recs.append(json.loads(line))
    return recs


def run_sample(rec: dict, *, dpi: int = 300, use_model: bool = True, merge_policy: str = "expand") -> dict:
    from pdf2md import tables as tables_mod

    doc = fitz.open(str(_REPO / rec["pdf"]))
    page = doc[rec["page"] - 1]
    rect = rec.get("bbox") or [0, 0, float(page.rect.width), float(page.rect.height)]
    frag = tables_mod.recognize_table(page, rect, dpi=dpi, use_model=use_model, merge_policy=merge_policy)
    doc.close()

    if frag is None:
        return {"recall": False, "teds": 0.0, "cer": 1.0, "quality": None, "source": None}
    pred_html = frag.get("html")
    if pred_html is None:
        # pymupdf 快路径无 html, 无法做结构对比 → 记召回但结构分缺失
        return {"recall": True, "teds": None, "cer": None, "quality": frag.get("structure_quality"),
                "source": frag.get("source")}
    gold_html = rec["gold_html"]
    return {
        "recall": True,
        "teds": round(teds(gold_html, pred_html), 4),
        "cer": round(cell_cer(gold_html, pred_html), 4),
        "quality": frag.get("structure_quality"),
        "source": frag.get("source"),
    }


def run_benchmark(recs: list[dict], **kw) -> dict:
    results = []
    for rec in recs:
        r = run_sample(rec, **kw)
        r["name"] = rec["name"]
        r["kind"] = rec.get("kind", "")
        results.append(r)

    n = len(results)
    recalls = [r for r in results if r["recall"]]
    teds_vals = [r["teds"] for r in results if r["teds"] is not None]
    cer_vals = [r["cer"] for r in results if r["cer"] is not None]
    aggregate = {
        "recall": round(len(recalls) / max(1, n), 4),
        "teds_mean": round(sum(teds_vals) / len(teds_vals), 4) if teds_vals else None,
        "cer_mean": round(sum(cer_vals) / len(cer_vals), 4) if cer_vals else None,
        "quality_gated_accuracy": round(
            sum(1 for r in results if r["recall"] and r["teds"] is not None and r["teds"] >= 0.9) / max(1, n), 4
        ),
    }
    return {"aggregate": aggregate, "samples": results}


def run_pipeline_level(recs: list[dict], **kw) -> dict:
    """全链路: convert_pdf 输出里是否存在与样本 bbox 重叠且结构达标的表格."""
    from pdf2md.pipeline import convert_pdf

    results = []
    for rec in recs:
        out = _REPO / "tests" / "benchmarks" / "out" / rec["name"]
        try:
            report = convert_pdf(str(_REPO / rec["pdf"]), str(out), max_pages=1, **kw)
        except Exception as exc:  # noqa: BLE001
            results.append({"name": rec["name"], "recall": False, "error": str(exc), "teds": 0.0})
            continue
        # 找与样本 bbox 重叠的 table item
        bbox = rec.get("bbox")
        best_teds = 0.0
        found = False
        for p in report["elements"]:
            for it in p["items"]:
                if it["type"] != "table" or bbox is None:
                    continue
                overlap = intersect_area(it["bbox_pdf"], bbox)
                if overlap > 0 and it.get("html"):
                    found = True
                    v = teds(rec["gold_html"], it["html"])
                    best_teds = max(best_teds, v)
        results.append({"name": rec["name"], "recall": found, "teds": round(best_teds, 4)})
    return {"aggregate": {"recall": round(sum(1 for r in results if r["recall"]) / max(1, len(results)), 4)},
            "samples": results}



def main() -> int:
    parser = argparse.ArgumentParser(description="表格识别基准 (recall / TEDS / cell CER)")
    parser.add_argument("--manifest", required=True, help="manifest.jsonl 路径")
    parser.add_argument("--out", default="benchmark_report.json", help="输出 JSON 报告")
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--no-model", action="store_true", help="跳过结构模型")
    parser.add_argument("--merge", default="expand", choices=["expand", "blank"])
    parser.add_argument("--level", default="table", choices=["table", "pipeline"],
                        help="table=直接 recognize_table; pipeline=全链路")
    args = parser.parse_args()

    recs = load_manifest(args.manifest)
    kw = {"dpi": args.dpi, "use_model": not args.no_model, "merge_policy": args.merge}
    if args.level == "pipeline":
        report = run_pipeline_level(recs)
    else:
        report = run_benchmark(recs, **kw)

    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    agg = report["aggregate"]
    print(f"样本数 {len(recs)} | recall {agg.get('recall')} | "
          f"teds {agg.get('teds_mean')} | cer {agg.get('cer_mean')} | "
          f"质量门控 {agg.get('quality_gated_accuracy')}")
    for r in report["samples"]:
        print(f"  {r['name']:<24} recall={r.get('recall')} teds={r.get('teds')} "
              f"cer={r.get('cer')} source={r.get('source')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
