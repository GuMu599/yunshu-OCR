"""layout.json 侧车写出 — 逐页元素 + bbox + 类型 + 页眉页脚 + 降级标记, 溯源用."""

from __future__ import annotations

import json
import os


def write_sidecar(out_dir: str, payload: dict) -> str:
    path = os.path.join(out_dir, "layout.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path
