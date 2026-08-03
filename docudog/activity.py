"""Append-only operational activity timeline (not P1/P2 audit)."""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any

from .reporter import _format_report_timestamp

logger = logging.getLogger(__name__)
_write_lock = threading.Lock()


def resolve_activity_log_path(cfg: dict[str, Any], report_path: str) -> str:
    paths = cfg.get("paths") or {}
    raw = str(paths.get("activity_log_path") or "").strip()
    if raw:
        return os.path.normpath(os.path.expandvars(raw))
    return os.path.join(
        os.path.dirname(os.path.normpath(os.path.expandvars(report_path))),
        "DocuDog_activity_log.md",
    )


def activity_enabled(cfg: dict[str, Any]) -> bool:
    raw = cfg.get("activity_settings")
    if isinstance(raw, dict) and "enabled" in raw:
        return bool(raw.get("enabled"))
    return True


def append_activity(
    cfg: dict[str, Any],
    report_path: str,
    prefix: str,
    message: str,
    *,
    when: datetime | None = None,
) -> None:
    """
    Append one activity line: ``[prefix] message``.
    Prefixes: classify | skip_hash | skip_filter | skip_extract | skip_empty |
    defer_active | defer_yield | audit | lineage | status.
    """
    if not activity_enabled(cfg):
        return
    path = resolve_activity_log_path(cfg, report_path)
    ts = _format_report_timestamp(when or datetime.now(timezone.utc))
    pref = (prefix or "event").strip().strip("[]")
    msg = " ".join(str(message).split())
    line = f"[{ts}] [{pref}] {msg}\n"
    header = (
        "# DocuDog activity log\n\n"
        "운영 타임라인 (append-only). P1/P2 감사는 `DocuDog_audit_log.md`를 사용.\n"
        "접두사: `[classify]` `[skip_hash]` `[skip_filter]` `[skip_extract]` "
        "`[skip_empty]` `[audit]` `[lineage]` 등.\n\n"
    )
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with _write_lock:
            is_new = not os.path.isfile(path)
            with open(path, "a", encoding="utf-8", newline="\n") as f:
                if is_new:
                    f.write(header)
                f.write(line)
    except OSError as e:
        logger.warning("Activity log append failed (%s): %s", path, e)
