"""基准执行器测试 (需要先运行 scripts/gen_table_benchmark.py 生成样本)"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import pytest

from pdf2md.benchmark import load_manifest, run_benchmark, run_sample  # noqa: E402

_REPO = Path(__file__).resolve().parent.parent.parent
_MANIFEST = _REPO / "tests" / "benchmarks" / "tables" / "manifest.jsonl"
_SAMPLE = _REPO / "tests" / "benchmarks" / "tables" / "synth" / "synth_numeric_right.pdf"


@pytest.mark.skipif(not _MANIFEST.exists(), reason="先运行 scripts/gen_table_benchmark.py")
def test_load_manifest():
    recs = load_manifest(str(_MANIFEST))
    assert len(recs) >= 4
    names = {r["name"] for r in recs}
    assert {"synth_grid", "synth_numeric_right", "synth_merged_header"} <= names


@pytest.mark.skipif(not _SAMPLE.exists(), reason="先运行 scripts/gen_table_benchmark.py")
def test_run_sample_native_geometry():
    rec = next(r for r in load_manifest(str(_MANIFEST)) if r["name"] == "synth_numeric_right")
    res = run_sample(rec, dpi=300)
    assert res["recall"] is True
    assert res["teds"] == 1.0
    assert res["cer"] == 0.0
    assert res["source"] == "geometry_native"


@pytest.mark.skipif(not _SAMPLE.exists(), reason="先运行 scripts/gen_table_benchmark.py")
def test_run_benchmark_aggregate():
    recs = load_manifest(str(_MANIFEST))
    report = run_benchmark(recs, dpi=300)
    agg = report["aggregate"]
    assert agg["recall"] == 1.0
    assert agg["teds_mean"] is not None and agg["teds_mean"] > 0.9
    assert len(report["samples"]) == len(recs)
