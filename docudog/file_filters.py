"""Document-only file gates: allowlist, junk denylist, incomplete downloads, settle age."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from . import watch_presets

# Office/Hangul/PDF text we can extract. Images and installers stay out.
DEFAULT_ALLOWED_EXTENSIONS: tuple[str, ...] = (
    ".txt",
    ".md",
    ".docx",
    ".xlsx",
    ".pptx",
    ".pdf",
    ".hwp",
    ".hwpx",
)

DEFAULT_BLOCKED_EXTENSIONS: tuple[str, ...] = (
    ".exe",
    ".msi",
    ".msix",
    ".msp",
    ".bat",
    ".cmd",
    ".com",
    ".scr",
    ".ps1",
    ".dll",
    ".sys",
    ".iso",
    ".img",
    ".dmg",
    ".apk",
    ".appx",
    ".msu",
    ".cab",
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".heic",
    ".heif",
    ".raw",
    ".svg",
    ".ico",
    ".mp3",
    ".wav",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".zip",
    ".7z",
    ".rar",
    ".gz",
    ".tar",
    ".lnk",
)

INCOMPLETE_SUFFIXES: tuple[str, ...] = (
    ".crdownload",
    ".part",
    ".partial",
    ".tmp",
    ".temp",
    ".download",
    ".opdownload",
    ".!qb",
    ".bc!",
)

SKIP_FILENAMES: frozenset[str] = frozenset(
    {
        "thumbs.db",
        "desktop.ini",
        ".ds_store",
    }
)


def _lower_exts(values: Any, fallback: tuple[str, ...]) -> set[str]:
    if not isinstance(values, list) or not values:
        return {e.lower() for e in fallback}
    out: set[str] = set()
    for item in values:
        text = str(item).strip().lower()
        if not text:
            continue
        if not text.startswith("."):
            text = "." + text
        out.add(text)
    return out or {e.lower() for e in fallback}


def _name_is_incomplete(name_lower: str) -> bool:
    return any(name_lower.endswith(suf) for suf in INCOMPLETE_SUFFIXES)


def _blocked_extensions(filters: dict[str, Any]) -> set[str]:
    extra = filters.get("blocked_extensions")
    blocked = {e.lower() for e in DEFAULT_BLOCKED_EXTENSIONS}
    if isinstance(extra, list):
        for item in extra:
            text = str(item).strip().lower()
            if not text:
                continue
            if not text.startswith("."):
                text = "." + text
            blocked.add(text)
    return blocked


def _file_age_seconds(path: str) -> float | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    newest = float(st.st_mtime)
    return max(0.0, time.time() - newest)


def passes_file_filters(config: dict[str, Any], path: str) -> bool:
    """True if this path is a document we may classify. Does not move the file."""
    filters = config.get("file_filters", {})
    if not isinstance(filters, dict):
        filters = {}
    name = Path(path).name
    name_lower = name.lower()
    if name_lower in SKIP_FILENAMES:
        return False
    if name.startswith("~$"):
        return False
    if _name_is_incomplete(name_lower):
        return False
    ext = Path(path).suffix.lower()
    if ext in _blocked_extensions(filters):
        return False
    allowed = _lower_exts(filters.get("allowed_extensions"), DEFAULT_ALLOWED_EXTENSIONS)
    if ext not in allowed:
        return False
    size = filters.get("size_limit", {})
    if not isinstance(size, dict):
        size = {}
    min_b = int(size.get("min_bytes", 0))
    max_b = int(size.get("max_bytes", 2**62))
    try:
        sz = os.path.getsize(path)
    except OSError:
        return False
    return min_b <= sz <= max_b


def settle_wait_reason(config: dict[str, Any], path: str) -> str | None:
    """
    If the file is still settling (especially Downloads), return a short reason.
    Caller should requeue; do not treat as a permanent skip.
    """
    filters = config.get("file_filters", {})
    if not isinstance(filters, dict):
        filters = {}
    try:
        min_age = float(filters.get("min_age_seconds", 0) or 0)
    except (TypeError, ValueError):
        min_age = 0.0
    try:
        downloads_age = float(filters.get("downloads_min_age_seconds", 120) or 0)
    except (TypeError, ValueError):
        downloads_age = 120.0
    need = min_age
    if watch_presets.path_is_under_downloads(config, path):
        need = max(need, downloads_age)
    if need <= 0:
        return None
    age = _file_age_seconds(path)
    if age is None:
        return "stat-failed"
    if age < need:
        return f"age {age:.0f}s < {need:.0f}s"
    return None
