#!/usr/bin/env python3
"""Smoke tests for folder presets and document-only file filters."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from docudog import file_filters, watch_presets  # noqa: E402


def _cfg(tmp: Path, **filters: object) -> dict:
    base = {
        "watch_settings": {
            "folder_presets": {
                "desktop": False,
                "downloads": False,
                "documents": False,
                "extra_directories": [],
            },
            "target_directories": [str(tmp)],
        },
        "file_filters": {
            "allowed_extensions": [".txt", ".md", ".docx", ".pdf", ".exe", ".jpg"],
            "min_age_seconds": 0,
            "downloads_min_age_seconds": 120,
            "size_limit": {"min_bytes": 8, "max_bytes": 10_000_000},
        },
    }
    base["file_filters"].update(filters)
    return base


def _write(path: Path, n: int = 32) -> str:
    path.write_bytes(b"d" * n)
    return str(path)


def main() -> int:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        cfg = _cfg(tmp)

        doc = _write(tmp / "memo.docx")
        assert file_filters.passes_file_filters(cfg, doc), "docx must pass"

        exe = _write(tmp / "Setup.exe")
        assert not file_filters.passes_file_filters(cfg, exe), "exe must be blocked"

        jpg = _write(tmp / "shot.jpg")
        assert not file_filters.passes_file_filters(cfg, jpg), "jpg must be blocked"

        busy = _write(tmp / "~$memo.docx")
        assert not file_filters.passes_file_filters(cfg, busy), "Office lock file skip"

        partial = _write(tmp / "report.pdf.crdownload")
        assert not file_filters.passes_file_filters(cfg, partial), "crdownload skip"

        roots = watch_presets.resolve_watch_roots(cfg)
        assert any(os.path.normcase(r) == os.path.normcase(str(tmp)) for r in roots)

        downloads = tmp / "Downloads"
        downloads.mkdir()
        fresh = _write(downloads / "invoice.pdf")
        orig = watch_presets.preset_path
        watch_presets.preset_path = lambda preset_id: str(downloads) if preset_id == "downloads" else orig(preset_id)  # type: ignore[assignment]
        try:
            reason = file_filters.settle_wait_reason(cfg, fresh)
            assert reason and "age" in reason, reason
        finally:
            watch_presets.preset_path = orig  # type: ignore[assignment]

        json_path = tmp / "config.json"
        json_path.write_text(
            json.dumps(
                {
                    "watch_settings": {
                        "folder_presets": {"desktop": False, "downloads": False, "documents": False}
                    }
                }
            ),
            encoding="utf-8",
        )
        watch_presets.persist_folder_preset(str(tmp), "desktop", True)
        saved = json.loads(json_path.read_text(encoding="utf-8"))
        assert saved["watch_settings"]["folder_presets"]["desktop"] is True

        old = time.time() - 400
        aged = downloads / "old.pdf"
        aged.write_bytes(b"d" * 32)
        os.utime(aged, (old, old))
        watch_presets.preset_path = lambda preset_id: str(downloads) if preset_id == "downloads" else orig(preset_id)  # type: ignore[assignment]
        try:
            assert file_filters.settle_wait_reason(cfg, str(aged)) is None
        finally:
            watch_presets.preset_path = orig  # type: ignore[assignment]

    print("watch preset and document-filter tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
