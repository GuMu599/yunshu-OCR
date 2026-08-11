"""Private process entry point for a fully isolated PDF conversion."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    request_path = Path(sys.argv[1])
    result_path = Path(sys.argv[2])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    try:
        from .pipeline import convert_pdf

        report = convert_pdf(**request, isolate=False)
        result = {"ok": True, "report": report}
        exit_code = 0
    except Exception as exc:  # noqa: BLE001 - serialized process boundary
        result = {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        exit_code = 2
    result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
