"""Run OCR adapters in an isolated child process with bounded resources."""

from __future__ import annotations

from dataclasses import asdict
from contextlib import redirect_stdout
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import psutil

try:
    from ocr_contracts import OCRCandidate, OCRJobResult, OCRRegionRequest
except ImportError:
    from .ocr_contracts import OCRCandidate, OCRJobResult, OCRRegionRequest


def run_ocr_job(request: OCRRegionRequest, timeout_seconds: float = 120) -> OCRJobResult:
    started = time.perf_counter()
    command = [sys.executable, str(Path(__file__).resolve()), "--worker"]
    with tempfile.TemporaryFile(mode="w+b") as output:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=output,
            # File-backed stdout avoids Windows pipe deadlocks on larger OCR JSON payloads.
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        peak_rss = 0
        payload = (json.dumps(request.to_dict(), ensure_ascii=True) + "\n").encode("ascii")
        if process.stdin is None:
            raise RuntimeError("OCR worker stdin unavailable")
        process.stdin.write(payload)
        process.stdin.close()
        ps_process = psutil.Process(process.pid)
        timed_out = False
        while process.poll() is None:
            try:
                peak_rss = max(peak_rss, ps_process.memory_info().rss)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            if peak_rss > request.max_ram_bytes or time.perf_counter() - started > timeout_seconds:
                timed_out = True
                _terminate_tree(process.pid)
                break
            time.sleep(0.02)
        process.wait(timeout=5)
        output.seek(0)
        stdout = output.read().decode("utf-8", errors="replace")
    duration_ms = round((time.perf_counter() - started) * 1000)
    alive = process.poll() is None
    if timed_out:
        error = "resource_limit_exceeded" if peak_rss > request.max_ram_bytes else "timeout"
        return OCRJobResult([], process.pid, process.returncode or -1, alive, peak_rss, duration_ms, error)
    try:
        worker_payload = json.loads(stdout.strip().splitlines()[-1]) if stdout.strip() else {}
    except (json.JSONDecodeError, IndexError):
        worker_payload = {}
    candidates = [OCRCandidate.from_dict(item) for item in worker_payload.get("regions", [])]
    return OCRJobResult(
        candidates, process.pid, int(process.returncode or 0), alive, peak_rss,
        duration_ms, worker_payload.get("error"),
    )


def _terminate_tree(pid: int) -> None:
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            child.kill()
        parent.kill()
        psutil.wait_procs(children + [parent], timeout=5)
    except psutil.NoSuchProcess:
        return


def _worker(request: OCRRegionRequest) -> tuple[list[OCRCandidate], str | None, int]:
    if request.engine == "fake":
        return [
            OCRCandidate(
                bbox_pdf=[float(value) for value in region], text="fake ocr text",
                confidence=1.0, engine="fake", character_confidences=[1.0] * 13,
            )
            for region in request.regions
        ], None, 0
    if request.engine in {"production", "rapidocr"}:
        return _run_rapidocr(request)
    return [], f"unsupported_engine:{request.engine}", 2


def _run_rapidocr(request: OCRRegionRequest) -> tuple[list[OCRCandidate], str | None, int]:
    adapter = Path(os.environ.get(
        "LITWISE_RAPIDOCR_ADAPTER",
        Path(__file__).resolve().parent.parent / "models" / "production" / "rapidocr-adapter",
    )).resolve()
    if not (adapter / "rapidocr").is_dir():
        return [], "model_missing:rapidocr", 2
    sys.path.insert(0, str(adapter))
    try:
        import fitz
        from rapidocr import RapidOCR
    except ImportError:
        return [], "model_missing:rapidocr", 2
    document = fitz.open(request.pdf_path)
    try:
        page = document.load_page(request.page - 1)
        engine = RapidOCR()
        candidates = []
        for region in request.regions:
            rect = fitz.Rect(*region) & page.rect
            if rect.is_empty:
                continue
            scale = max(1.0, float(request.dpi) / 72.0)
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
            output = engine(pixmap.tobytes("png"))
            texts = list(output.txts or ())
            scores = [float(value) for value in (output.scores or ())]
            text = "\n".join(value.strip() for value in texts if value and value.strip())
            if not text:
                continue
            raw_confidence = sum(scores) / len(scores) if scores else 0.0
            confidence = _calibrate_ocr_confidence(text, raw_confidence)
            candidates.append(OCRCandidate(
                bbox_pdf=[float(value) for value in region], text=text,
                confidence=confidence, engine="rapidocr",
                # RapidOCR exposes line scores, not reliable per-character scores.
                character_confidences=[],
            ))
        return candidates, None, 0
    except Exception as exc:
        return [], f"rapidocr_failed:{str(exc)[:200]}", 2
    finally:
        document.close()


def _calibrate_ocr_confidence(text: str, raw_confidence: float) -> float:
    replacement = text.count("\ufffd")
    suspicious_tokens = ("\u951f", "\u70eb\u70eb", "\ufffd", "\ufffd\ufffd")
    mojibake = sum(text.count(token) for token in suspicious_tokens)
    visible = max(len(text.strip()), 1)
    damage_ratio = min(1.0, (replacement + mojibake) / visible)
    # A single OCR engine cannot independently verify academic source text.
    calibrated = min(float(raw_confidence), 0.94) * (1.0 - damage_ratio * 8)
    return round(max(0.0, min(0.94, calibrated)), 4)


def _worker_main() -> int:
    line = sys.stdin.readline()
    request = OCRRegionRequest.from_dict(json.loads(line))
    # Reserve stdout for the one-line JSON protocol; third-party OCR logs are discarded.
    with open(os.devnull, "w", encoding="utf-8") as sink, redirect_stdout(sink):
        regions, error, exit_code = _worker(request)
    # ASCII-escaped JSON keeps the worker protocol independent of the Windows console code page.
    print(json.dumps({"regions": [asdict(item) for item in regions], "error": error}, ensure_ascii=True), flush=True)
    return exit_code


if __name__ == "__main__":
    if "--worker" in sys.argv:
        raise SystemExit(_worker_main())
