"""Hard boundaries for converting untrusted PDFs.

The parent process owns the wall-clock, process-tree memory and output-size
budgets.  The conversion process validates file/page/pixel/region budgets
before expensive rendering or inference.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

import fitz
import psutil


class ResourceLimitError(RuntimeError):
    """A deterministic conversion resource budget was exceeded."""


@dataclass(frozen=True)
class ConversionLimits:
    max_input_bytes: int = 512 * 1024**2
    max_pages: int = 500
    max_dpi: int = 600
    max_page_pixels: int = 100_000_000
    max_total_pixels: int = 1_500_000_000
    max_regions_per_page: int = 2_000
    max_output_bytes: int = 2 * 1024**3
    max_runtime_seconds: float = 30 * 60
    max_ram_bytes: int = 8 * 1024**3

    @classmethod
    def from_system(cls) -> "ConversionLimits":
        total = int(psutil.virtual_memory().total)
        return cls(max_ram_bytes=max(2 * 1024**3, min(8 * 1024**3, int(total * 0.45))))

    @classmethod
    def coerce(cls, value: "ConversionLimits | dict[str, Any] | None") -> "ConversionLimits":
        if value is None:
            return cls.from_system()
        if isinstance(value, cls):
            return value
        allowed = {item.name for item in fields(cls)}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"unknown conversion limit(s): {', '.join(sorted(unknown))}")
        return cls(**value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate_input(
        self,
        pdf_path: str | os.PathLike,
        *,
        dpi: int,
        image_dpi: int,
        formula_dpi: int,
        max_pages: int | None = None,
    ) -> dict[str, int]:
        path = Path(pdf_path).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        input_bytes = path.stat().st_size
        if input_bytes > self.max_input_bytes:
            raise ResourceLimitError(
                f"resource_limit:input_bytes — {input_bytes} > {self.max_input_bytes}"
            )
        for name, value in (("dpi", dpi), ("image_dpi", image_dpi), ("formula_dpi", formula_dpi)):
            if not isinstance(value, int) or value <= 0 or value > self.max_dpi:
                raise ResourceLimitError(
                    f"resource_limit:{name} — expected 1..{self.max_dpi}, got {value}"
                )
        if max_pages is not None and (max_pages <= 0 or max_pages > self.max_pages):
            raise ResourceLimitError(
                f"resource_limit:max_pages — expected 1..{self.max_pages}, got {max_pages}"
            )

        document = fitz.open(str(path))
        try:
            selected_pages = len(document) if max_pages is None else min(max_pages, len(document))
            if selected_pages > self.max_pages:
                raise ResourceLimitError(
                    f"resource_limit:pages — {selected_pages} > {self.max_pages}"
                )
            render_dpi = max(dpi, image_dpi, formula_dpi)
            total_pixels = 0
            for index in range(selected_pages):
                rect = document[index].rect
                width = max(0, int(rect.width * render_dpi / 72.0 + 0.999))
                height = max(0, int(rect.height * render_dpi / 72.0 + 0.999))
                pixels = width * height
                if pixels > self.max_page_pixels:
                    raise ResourceLimitError(
                        f"resource_limit:page_pixels — page {index + 1}: "
                        f"{pixels} > {self.max_page_pixels}"
                    )
                total_pixels += pixels
                if total_pixels > self.max_total_pixels:
                    raise ResourceLimitError(
                        f"resource_limit:total_pixels — {total_pixels} > {self.max_total_pixels}"
                    )
        finally:
            document.close()
        return {
            "input_bytes": input_bytes,
            "pages": selected_pages,
            "total_pixels": total_pixels,
        }

    def validate_regions(self, regions_by_page: list[list[dict]]) -> None:
        for index, regions in enumerate(regions_by_page, 1):
            if len(regions) > self.max_regions_per_page:
                raise ResourceLimitError(
                    f"resource_limit:regions — page {index}: "
                    f"{len(regions)} > {self.max_regions_per_page}"
                )

    def validate_output(self, output_dir: str | os.PathLike) -> int:
        size = directory_size(output_dir)
        if size > self.max_output_bytes:
            raise ResourceLimitError(
                f"resource_limit:output_bytes — {size} > {self.max_output_bytes}"
            )
        return size


def directory_size(path: str | os.PathLike) -> int:
    root = Path(path)
    if not root.exists():
        return 0
    total = 0
    for entry in root.rglob("*"):
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            continue
    return total


def _terminate_tree(pid: int) -> None:
    try:
        parent = psutil.Process(pid)
        processes = parent.children(recursive=True) + [parent]
        for process in processes:
            try:
                process.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        psutil.wait_procs(processes, timeout=5)
    except psutil.NoSuchProcess:
        pass


def _tree_rss(pid: int) -> int:
    try:
        parent = psutil.Process(pid)
        processes = [parent, *parent.children(recursive=True)]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return 0
    total = 0
    for process in processes:
        try:
            total += int(process.memory_info().rss)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return total


def _assign_windows_job_memory_limit(process: subprocess.Popen, max_ram_bytes: int):
    """Put the worker in a kill-on-close Job Object with hard memory limits."""
    if os.name != "nt":
        return None
    import ctypes  # noqa: PLC0415
    from ctypes import wintypes  # noqa: PLC0415

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
        )]

    class BASIC_LIMITS(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class EXTENDED_LIMITS(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BASIC_LIMITS),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = EXTENDED_LIMITS()
    info.BasicLimitInformation.LimitFlags = 0x00000100 | 0x00000200 | 0x00002000
    info.ProcessMemoryLimit = max_ram_bytes
    info.JobMemoryLimit = max_ram_bytes
    if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
        kernel32.CloseHandle(job)
        return None
    if not kernel32.AssignProcessToJobObject(job, wintypes.HANDLE(process._handle)):
        kernel32.CloseHandle(job)
        return None
    return job


def _close_windows_handle(handle) -> None:
    if handle and os.name == "nt":
        import ctypes  # noqa: PLC0415
        ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(handle)


def run_bounded_process(
    command: list[str],
    *,
    limits: ConversionLimits,
    output_dir: str | os.PathLike,
    stdout=None,
    stderr=None,
) -> subprocess.Popen:
    """Run a process under hard/best-effort OS and continuously checked quotas."""
    process = subprocess.Popen(
        command,
        stdout=stdout,
        stderr=stderr,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    job_handle = _assign_windows_job_memory_limit(process, limits.max_ram_bytes)
    started = time.monotonic()
    peak_rss = 0
    violation: str | None = None
    try:
        while process.poll() is None:
            elapsed = time.monotonic() - started
            peak_rss = max(peak_rss, _tree_rss(process.pid))
            if elapsed > limits.max_runtime_seconds:
                violation = (
                    f"resource_limit:runtime_seconds — {elapsed:.2f} > "
                    f"{limits.max_runtime_seconds}"
                )
                break
            if peak_rss > limits.max_ram_bytes:
                violation = f"resource_limit:ram_bytes — {peak_rss} > {limits.max_ram_bytes}"
                break
            output_bytes = directory_size(output_dir)
            if output_bytes > limits.max_output_bytes:
                violation = (
                    f"resource_limit:output_bytes — {output_bytes} > "
                    f"{limits.max_output_bytes}"
                )
                break
            time.sleep(0.02)
        if violation:
            _terminate_tree(process.pid)
            process.wait(timeout=5)
            raise ResourceLimitError(violation)
        process.wait()
        return process
    finally:
        _close_windows_handle(job_handle)


def run_isolated_conversion(payload: dict[str, Any], limits: ConversionLimits) -> dict:
    """Execute the complete parser/render/model pipeline outside the caller."""
    output_dir = Path(payload["output_dir"]).expanduser().resolve()
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pdf2md-worker-") as temp:
        temp_dir = Path(temp)
        request_path = temp_dir / "request.json"
        result_path = temp_dir / "result.json"
        request = dict(payload)
        request["resource_limits"] = limits.to_dict()
        request_path.write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        with tempfile.TemporaryFile(mode="w+b") as stdout, tempfile.TemporaryFile(mode="w+b") as stderr:
            process = run_bounded_process(
                [sys.executable, "-m", "pdf2md.conversion_worker", str(request_path), str(result_path)],
                limits=limits,
                output_dir=output_dir,
                stdout=stdout,
                stderr=stderr,
            )
            if not result_path.is_file():
                stderr.seek(0)
                detail = stderr.read().decode("utf-8", errors="replace")[-2000:]
                raise RuntimeError(
                    f"conversion_worker_failed: exit={process.returncode}; {detail}"
                )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if not result.get("ok"):
            error_type = result.get("error_type", "RuntimeError")
            message = result.get("error", "conversion worker failed")
            if error_type == "ResourceLimitError":
                raise ResourceLimitError(message)
            raise RuntimeError(message)
        return result["report"]
