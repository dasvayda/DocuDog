"""Windows idle detection (GetLastInputInfo) and filesystem watching (watchdog)."""

from __future__ import annotations

import ctypes
import logging
import os
import platform
import queue
import time
from ctypes import wintypes
from collections.abc import Callable
from pathlib import Path
from typing import Any, Iterable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from . import paths_util

logger = logging.getLogger(__name__)

_non_windows_idle_warning_emitted = False

# Windows API: last keyboard/mouse input
if platform.system() == "Windows":
    _user32 = ctypes.windll.user32

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("dwTime", wintypes.DWORD),
        ]
else:  # pragma: no cover - non-Windows fallback for import/tests
    _user32 = None
    LASTINPUTINFO = None  # type: ignore[misc, assignment]

_KERNEL32 = ctypes.windll.kernel32 if platform.system() == "Windows" else None


def seconds_since_last_input() -> float:
    """Return seconds since last user keyboard/mouse input (Windows), or 0.0 if unknown."""
    global _non_windows_idle_warning_emitted
    if platform.system() != "Windows" or _user32 is None or _KERNEL32 is None:
        if not _non_windows_idle_warning_emitted:
            logger.warning(
                "GetLastInputInfo is only supported on Windows; assuming active user (0s idle)."
            )
            _non_windows_idle_warning_emitted = True
        return 0.0
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if not _user32.GetLastInputInfo(ctypes.byref(info)):
        logger.warning("GetLastInputInfo failed; assuming user active.")
        return 0.0
    tick_count = _KERNEL32.GetTickCount()
    elapsed_ms = tick_count - info.dwTime
    if elapsed_ms < 0:
        elapsed_ms = 0
    return elapsed_ms / 1000.0


def _path_matches_exclude(normalized_path: str, exclude_dirs: Iterable[str]) -> bool:
    parts = {p.lower() for p in Path(normalized_path).parts}
    for ex in exclude_dirs:
        if ex.lower() in parts:
            return True
    return False


def _passes_quick_filter(
    path: str,
    allowed_exts: set[str],
    min_bytes: int,
    max_bytes: int,
) -> bool:
    ext = Path(path).suffix.lower()
    if ext not in allowed_exts:
        return False
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    return min_bytes <= size <= max_bytes


class _DocuDogWatchHandler(FileSystemEventHandler):
    """Enqueue created/modified files that pass quick filters."""

    def __init__(
        self,
        file_queue: queue.Queue[tuple[str, float]],
        exclude_directories: list[str],
        allowed_extensions: set[str],
        min_bytes: int,
        max_bytes: int,
        on_seen: Callable[[str, float], None] | None = None,
        *,
        dedupe_seconds: float = 2.0,
    ) -> None:
        super().__init__()
        self._file_queue = file_queue
        self._exclude_directories = exclude_directories
        self._allowed_extensions = allowed_extensions
        self._min_bytes = min_bytes
        self._max_bytes = max_bytes
        self._on_seen = on_seen
        self._dedupe_seconds = max(0.0, float(dedupe_seconds))
        self._recent: dict[str, float] = {}

    def _maybe_enqueue(self, src_path: str | bytes | None) -> None:
        if not src_path or isinstance(src_path, bytes):
            return
        try:
            normalized = paths_util.normalize_fs_path(src_path)
        except OSError:
            return
        if _path_matches_exclude(normalized, self._exclude_directories):
            return
        if not os.path.isfile(normalized):
            return
        if not _passes_quick_filter(
            normalized, self._allowed_extensions, self._min_bytes, self._max_bytes
        ):
            return
        t = time.time()
        if self._dedupe_seconds > 0:
            last = self._recent.get(normalized)
            if last is not None and (t - last) < self._dedupe_seconds:
                logger.debug("Dedupe skip (recent event): %s", normalized)
                return
            self._recent[normalized] = t
            # prune occasionally
            if len(self._recent) > 4000:
                cutoff = t - max(60.0, self._dedupe_seconds * 10)
                self._recent = {k: v for k, v in self._recent.items() if v >= cutoff}
        if self._on_seen is not None:
            self._on_seen(normalized, t)
        self._file_queue.put((normalized, t))
        logger.debug("Queued for later analysis: %s", normalized)

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._maybe_enqueue(event.src_path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        self._maybe_enqueue(event.src_path)


def expand_watch_dirs(config: dict[str, Any]) -> list[str]:
    """Return absolute watch roots from config (expandvars + UNC-safe normalize)."""
    watch = config.get("watch_settings", {})
    raw_dirs: list[str] = watch.get("target_directories", [])
    out: list[str] = []
    for d in raw_dirs:
        expanded = paths_util.normalize_fs_path(str(d))
        out.append(expanded)
        if paths_util.is_unc_path(expanded):
            logger.info(
                "UNC/NAS watch root configured: %s "
                "(single state/report; concurrent writers may hit sharing locks — retries apply)",
                expanded,
            )
    return out


def start_observer(
    config: dict[str, Any],
    file_queue: queue.Queue[tuple[str, float]],
    on_seen: Callable[[str, float], None] | None = None,
) -> Observer:
    """Start recursive watchdog observers for all target_directories."""
    watch = config.get("watch_settings", {})
    exclude = list(watch.get("exclude_directories", []))
    filters = config.get("file_filters", {})
    exts = {e.lower() for e in filters.get("allowed_extensions", [])}
    size = filters.get("size_limit", {})
    min_b = int(size.get("min_bytes", 0))
    max_b = int(size.get("max_bytes", 2**62))
    try:
        dedupe = float(watch.get("event_dedupe_seconds", 2.0))
    except (TypeError, ValueError):
        dedupe = 2.0

    handler = _DocuDogWatchHandler(
        file_queue, exclude, exts, min_b, max_b, on_seen, dedupe_seconds=dedupe
    )
    observer = Observer()

    for root in expand_watch_dirs(config):
        if not os.path.isdir(root):
            logger.warning("Watch directory missing (will not observe): %s", root)
            continue
        try:
            observer.schedule(handler, root, recursive=True)
            logger.debug("Watching recursively: %s", root)
        except Exception as e:
            logger.warning("Failed to schedule watch on %s: %s", root, e)

    observer.start()
    return observer


def seed_queue_from_existing_files(
    config: dict[str, Any],
    file_queue: queue.Queue[tuple[str, float]],
    on_seen: Callable[[str, float], None] | None = None,
) -> int:
    """
    Enqueue files already on disk under watch roots (watchdog only sees new changes).

    Uses the same extension/size/exclude rules as the live watcher.
    """
    watch = config.get("watch_settings", {})
    exclude = list(watch.get("exclude_directories", []))
    exclude_lower = {e.lower() for e in exclude}
    filters = config.get("file_filters", {})
    exts = {e.lower() for e in filters.get("allowed_extensions", [])}
    size = filters.get("size_limit", {})
    min_b = int(size.get("min_bytes", 0))
    max_b = int(size.get("max_bytes", 2**62))

    count = 0
    for root in expand_watch_dirs(config):
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d.lower() not in exclude_lower]
            norm_dir = os.path.normpath(dirpath)
            if _path_matches_exclude(norm_dir, exclude):
                dirnames[:] = []
                continue
            for name in filenames:
                full = os.path.join(dirpath, name)
                try:
                    norm = paths_util.normalize_fs_path(full)
                except OSError:
                    continue
                if _path_matches_exclude(norm, exclude):
                    continue
                if not os.path.isfile(norm):
                    continue
                if not _passes_quick_filter(norm, exts, min_b, max_b):
                    continue
                t = time.time()
                if on_seen is not None:
                    on_seen(norm, t)
                file_queue.put((norm, t))
                count += 1
                logger.debug("Startup scan queued: %s", norm)

    if count:
        logger.info("Startup scan: %s file(s) enqueued for analysis.", count)
    else:
        logger.debug(
            "Startup scan: no files matched (check path, extensions, size >= %s bytes).",
            min_b,
        )
    return count


def sleep_while_busy(idle_trigger_seconds: float, poll_seconds: float = 0.5) -> None:
    """Block until the system has been idle for at least idle_trigger_seconds."""
    last_log = 0.0
    while seconds_since_last_input() < idle_trigger_seconds:
        now = time.monotonic()
        idle_sec = seconds_since_last_input()
        if now - last_log >= 30.0:
            logger.debug(
                "Waiting for user idle: %.1fs since last input (need %.1fs).",
                idle_sec,
                idle_trigger_seconds,
            )
            last_log = now
        time.sleep(poll_seconds)
