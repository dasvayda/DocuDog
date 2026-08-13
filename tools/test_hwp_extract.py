#!/usr/bin/env python3
"""Smoke: HWPX zip fixture -> extract_document_text; invalid .hwp skip path."""

from __future__ import annotations

import os
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from docudog import router  # noqa: E402

_MARKER = "DocuDog HWPX fixture Q2 planning draft"


def write_min_hwpx(path: str, body: str) -> None:
    # File size must exceed default file_filters.size_limit.min_bytes (1024).
    pad = ("Lorem padding for DocuDog size gate. " * 40).strip()
    section = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<section>\n"
        f"  <p><t>{body}</t></p>\n"
        "  <tbl>\n"
        "    <tr><tc><p><t>Item</t></p></tc><tc><p><t>Owner</t></p></tc></tr>\n"
        "    <tr><tc><p><t>Edge AI pilot docs</t></p></tc>"
        "<tc><p><t>Internal</t></p></tc></tr>\n"
        "  </tbl>\n"
        f"  <p><t>{pad}</t></p>\n"
        "</section>\n"
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/hwp+zip", compress_type=zipfile.ZIP_STORED)
        zf.writestr(
            "version.xml",
            '<version major="1" minor="1" micro="0" buildNumber="0"/>',
        )
        zf.writestr("Contents/section0.xml", section)
        # Keep the packaged file above default min_bytes (ZIP would otherwise compress under 1 KiB).
        zf.writestr(
            "Contents/_docudog_size_pad.bin",
            b"X" * 1200,
            compress_type=zipfile.ZIP_STORED,
        )


def _fail(msg: str) -> int:
    print(f"test_hwp_extract: FAIL — {msg}", file=sys.stderr)
    return 1


def main() -> int:
    fixture = os.path.join(ROOT, "fixtures", "sample_internal_memo.hwpx")
    if os.path.isfile(fixture):
        text, reason = router.extract_document_text(fixture)
        if reason:
            return _fail(f"committed hwpx skipped: {reason}")
        if not text or _MARKER not in text:
            return _fail("committed hwpx missing expected body text")
        if "Edge AI pilot docs" not in text:
            return _fail("committed hwpx missing table cell text")
        print("test_hwp_extract: fixture OK", len(text), "chars")

    fd, tmp = tempfile.mkstemp(suffix=".hwpx", prefix="docudog_hwp_")
    os.close(fd)
    try:
        write_min_hwpx(tmp, _MARKER)
        text, reason = router.extract_document_text(tmp)
        if reason:
            return _fail(f"temp hwpx skipped: {reason}")
        if not text or _MARKER not in text:
            return _fail("temp hwpx extract empty or missing marker")
        print("test_hwp_extract: generated hwpx OK")
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass

    junk = os.path.join(tempfile.gettempdir(), "docudog_not_hwp.hwp")
    with open(junk, "wb") as f:
        f.write(b"not an ole or zip file" + b"x" * 64)
    try:
        text, reason = router.extract_document_text(junk)
        if text:
            return _fail("garbage .hwp should not yield body text")
        if not reason:
            return _fail("garbage .hwp should set skip_reason")
        print("test_hwp_extract: invalid hwp skip OK -", reason[:80])
    finally:
        try:
            os.unlink(junk)
        except OSError:
            pass

    print("test_hwp_extract: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
