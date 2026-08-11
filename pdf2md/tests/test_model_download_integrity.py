"""Downloaded model bytes are verified before becoming visible to loaders."""

import logging
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO / "models" / "production" / "rapidocr-adapter"))
sys.path.insert(0, str(_REPO / "models" / "production" / "table-adapter"))

from rapid_table.utils.download_file import (  # noqa: E402
    DownloadFile as TableDownload,
    DownloadFileException as TableDownloadError,
    DownloadFileInput as TableInput,
)
from rapidocr.utils.download_file import (  # noqa: E402
    DownloadFile as OCRDownload,
    DownloadFileException as OCRDownloadError,
    DownloadFileInput as OCRInput,
)


class _Response:
    headers = {"content-length": "9"}

    @staticmethod
    def iter_content(chunk_size=1024):
        del chunk_size
        yield b"tampered!"


@pytest.mark.parametrize(
    ("downloader", "input_type", "error_type"),
    [
        (OCRDownload, OCRInput, OCRDownloadError),
        (TableDownload, TableInput, TableDownloadError),
    ],
)
def test_download_checksum_is_verified_before_atomic_publish(
    monkeypatch, tmp_path, downloader, input_type, error_type
):
    target = tmp_path / "model.onnx"
    monkeypatch.setattr(downloader, "_make_http_request", lambda *args: _Response())
    request = input_type(
        file_url="https://models.invalid/model.onnx",
        save_path=target,
        logger=logging.getLogger("test"),
        sha256="0" * 64,
    )

    with pytest.raises(error_type, match="checksum"):
        downloader.run(request)

    assert not target.exists()
    assert not list(tmp_path.glob("*.part"))
