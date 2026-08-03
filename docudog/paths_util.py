"""Path helpers — UNC/NAS friendly normalize + short open retries."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def is_unc_path(path: str) -> bool:
    p = (path or "").replace("/", "\\")
    return p.startswith("\\\\") and not p.startswith("\\\\?\\")


def normalize_fs_path(path: str) -> str:
    """
    Expand env vars and normalize. Prefer keeping UNC roots intact.
    abspath on some UNC forms can still work on Windows; if it fails, normpath only.
    """
    raw = os.path.expandvars((path or "").strip())
    if not raw:
        return raw
    # forward-slash UNC paste: //server/share -> \\server\share
    if raw.startswith("//") and not raw.startswith("//?/"):
        raw = "\\\\" + raw[2:].replace("/", "\\")
    try:
        if is_unc_path(raw) or raw.startswith("\\\\?\\UNC\\"):
            return os.path.normpath(raw)
        return os.path.normpath(os.path.abspath(raw))
    except OSError:
        return os.path.normpath(raw)


def retry_settings(cfg: dict[str, Any] | None) -> tuple[int, float]:
    watch = (cfg or {}).get("watch_settings") if isinstance(cfg, dict) else {}
    if not isinstance(watch, dict):
        watch = {}
    try:
        attempts = int(watch.get("file_open_retries", 3))
    except (TypeError, ValueError):
        attempts = 3
    try:
        delay = float(watch.get("file_open_retry_seconds", 0.4))
    except (TypeError, ValueError):
        delay = 0.4
    return max(1, attempts), max(0.0, delay)


def with_file_retry(
    cfg: dict[str, Any] | None,
    label: str,
    fn: Callable[[], T],
) -> T:
    """Retry on transient Windows sharing / network IO errors."""
    attempts, delay = retry_settings(cfg)
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return fn()
        except OSError as e:
            last = e
            winerr = getattr(e, "winerror", None)
            # 32 = sharing violation, 33 = lock violation, 53/64 network
            transient = winerr in (32, 33, 53, 64, 59, 121) or e.errno in (
                11,
                13,
                16,
            )
            if not transient or i + 1 >= attempts:
                raise
            logger.debug(
                "File retry %s/%s (%s): %s — %s",
                i + 1,
                attempts,
                label,
                e,
                "UNC/network or sharing lock",
            )
            if delay:
                time.sleep(delay)
    assert last is not None
    raise last
