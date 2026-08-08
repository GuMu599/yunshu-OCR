import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


def test_ocr_worker_process_exits_and_returns_region_candidates(tmp_path):
    from ocr_contracts import OCRRegionRequest
    from ocr_worker import run_ocr_job

    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    request = OCRRegionRequest(
        job_id="j1", pdf_path=str(pdf), page=1,
        regions=[[10, 20, 200, 100]], engine="fake", language="zh",
        dpi=220, max_ram_bytes=512 * 1024 * 1024,
    )

    result = run_ocr_job(request, timeout_seconds=10)

    assert result.worker_exit_code == 0
    assert result.worker_pid is not None
    assert result.worker_alive_after_join is False
    assert result.regions[0].bbox_pdf == [10, 20, 200, 100]
    assert result.regions[0].engine == "fake"


def test_ocr_worker_reports_unknown_engine_without_hanging(tmp_path):
    from ocr_contracts import OCRRegionRequest
    from ocr_worker import run_ocr_job

    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    request = OCRRegionRequest(
        job_id="j2", pdf_path=str(pdf), page=1, regions=[],
        engine="missing", language="zh", dpi=220, max_ram_bytes=128 * 1024 * 1024,
    )

    result = run_ocr_job(request, timeout_seconds=10)

    assert result.worker_exit_code != 0
    assert result.worker_alive_after_join is False
    assert result.error == "unsupported_engine:missing"


def test_production_worker_reports_missing_adapter_explicitly(tmp_path, monkeypatch):
    from ocr_contracts import OCRRegionRequest
    import ocr_worker

    monkeypatch.setenv("LITWISE_RAPIDOCR_ADAPTER", str(tmp_path / "missing"))
    request = OCRRegionRequest(
        job_id="production", pdf_path=str(tmp_path / "paper.pdf"), page=1,
        regions=[[0, 0, 100, 100]], engine="production", language="zh",
        dpi=220, max_ram_bytes=1024**3,
    )

    regions, error, exit_code = ocr_worker._worker(request)

    assert regions == []
    assert error == "model_missing:rapidocr"
    assert exit_code == 2
