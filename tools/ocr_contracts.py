"""Serializable contracts for isolated OCR worker jobs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class OCRRegionRequest:
    job_id: str
    pdf_path: str
    page: int
    regions: list[list[float]]
    engine: str
    language: str
    dpi: int
    max_ram_bytes: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OCRRegionRequest":
        return cls(**payload)


@dataclass(frozen=True)
class OCRCandidate:
    bbox_pdf: list[float]
    text: str
    confidence: float
    engine: str
    character_confidences: list[float] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OCRCandidate":
        return cls(**payload)


@dataclass(frozen=True)
class OCRJobResult:
    regions: list[OCRCandidate]
    worker_pid: int | None
    worker_exit_code: int
    worker_alive_after_join: bool
    peak_rss_bytes: int
    duration_ms: int
    error: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "OCRJobResult":
        return cls(
            regions=[OCRCandidate.from_dict(item) for item in payload.get("regions", [])],
            worker_pid=payload.get("worker_pid"),
            worker_exit_code=int(payload.get("worker_exit_code") or 0),
            worker_alive_after_join=bool(payload.get("worker_alive_after_join")),
            peak_rss_bytes=int(payload.get("peak_rss_bytes") or 0),
            duration_ms=int(payload.get("duration_ms") or 0),
            error=payload.get("error"),
        )
