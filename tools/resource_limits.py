"""Resource policies for short-lived OCR and document workers."""

from __future__ import annotations

from dataclasses import dataclass

import psutil


def physical_memory_bytes() -> int:
    return int(psutil.virtual_memory().total)


@dataclass(frozen=True)
class ResourcePolicy:
    soft_ram_bytes: int = 2 * 1024**3
    hard_ram_bytes: int = 3 * 1024**3
    batch_pages: int = 1
    working_dpi: int = 300
    final_asset_dpi: int = 300
    soft_vram_bytes: int = 6 * 1024**3

    @classmethod
    def from_system(cls) -> "ResourcePolicy":
        memory = physical_memory_bytes()
        return cls(
            soft_ram_bytes=min(int(memory * 0.25), 8 * 1024**3),
            hard_ram_bytes=min(int(memory * 0.35), 10 * 1024**3),
            batch_pages=1 if memory < 16 * 1024**3 else 2,
        )

    def after_oom(self, *, batch_pages: int, working_dpi: int) -> "ResourcePolicy":
        next_dpi = 220 if working_dpi > 220 else max(150, working_dpi - 40)
        return ResourcePolicy(
            soft_ram_bytes=self.soft_ram_bytes,
            hard_ram_bytes=self.hard_ram_bytes,
            batch_pages=1,
            working_dpi=next_dpi,
            final_asset_dpi=self.final_asset_dpi,
            soft_vram_bytes=self.soft_vram_bytes,
        )
