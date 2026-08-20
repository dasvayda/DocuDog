"""Stable file_id on state file records (path is placement, not identity)."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


def new_id() -> str:
    return str(uuid.uuid4())


def thread_settings(cfg: dict[str, Any] | None) -> dict[str, Any]:
    raw = (cfg or {}).get("thread_settings")
    ts = raw if isinstance(raw, dict) else {}
    hours = ts.get("rename_window_hours", 24)
    try:
        hours_n = float(hours)
    except (TypeError, ValueError):
        hours_n = 24.0
    return {
        "enabled": bool(ts.get("enabled", True)),
        "max_threads": max(3, min(80, int(ts.get("max_threads", 20)))),
        "max_members": max(3, min(40, int(ts.get("max_members", 12)))),
        "include_conversations": bool(ts.get("include_conversations", True)),
        "min_rel_depth": max(1, min(8, int(ts.get("min_rel_depth", 1)))),
        "header_limit": max(3, min(24, int(ts.get("header_limit", 10)))),
        "unfold_members": max(2, min(20, int(ts.get("unfold_members", 8)))),
        "rename_window_hours": max(1.0, min(168.0, hours_n)),
    }


def ensure_file_id(meta: dict[str, Any]) -> str:
    fid = str(meta.get("file_id") or "").strip()
    if not fid:
        fid = new_id()
        meta["file_id"] = fid
    return fid


def ensure_all_file_ids(state: dict[str, Any]) -> int:
    """Assign missing UUIDs. Returns how many were created."""
    files = state.get("files")
    if not isinstance(files, dict):
        return 0
    n = 0
    for meta in files.values():
        if not isinstance(meta, dict):
            continue
        if not str(meta.get("file_id") or "").strip():
            meta["file_id"] = new_id()
            n += 1
    return n


def find_path_by_file_id(files: dict[str, Any], file_id: str) -> str | None:
    want = str(file_id or "").strip()
    if not want:
        return None
    for path, meta in files.items():
        if isinstance(meta, dict) and str(meta.get("file_id") or "") == want:
            return path
    return None


def _parse_utc(iso: str) -> datetime | None:
    s = (iso or "").strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _within_hours(iso: str, hours: float) -> bool:
    dt = _parse_utc(iso)
    if dt is None:
        return False
    now = datetime.now(timezone.utc)
    return (now - dt) <= timedelta(hours=hours)


def adopt_rename(
    files_state: dict[str, Any],
    new_path: str,
    digest: str,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    If this path is new but exactly one vanished path has the same SHA-256
    within the rename window, move that record (keep file_id).

    Copies that still exist on disk are ignored so two live files never share an id.
    """
    if new_path in files_state:
        return None
    digest = str(digest or "").strip()
    if not digest:
        return None
    hours = thread_settings(cfg)["rename_window_hours"]
    candidates: list[tuple[str, dict[str, Any]]] = []
    for path, meta in list(files_state.items()):
        if not isinstance(meta, dict):
            continue
        if str(meta.get("sha256") or "") != digest:
            continue
        if os.path.normcase(path) == os.path.normcase(new_path):
            continue
        try:
            if os.path.isfile(path):
                continue
        except OSError:
            pass
        ts = str(meta.get("last_analyzed_utc") or meta.get("last_checked_utc") or "")
        if not _within_hours(ts, hours):
            continue
        candidates.append((path, meta))
    if len(candidates) != 1:
        if len(candidates) > 1:
            logger.info(
                "file_id split: %s vanished paths share sha256 (not a rename)",
                len(candidates),
            )
        return None
    old_path, meta = candidates[0]
    files_state.pop(old_path, None)
    ensure_file_id(meta)
    files_state[new_path] = meta
    logger.info(
        "Adopted file_id on rename: %s -> %s",
        os.path.basename(old_path),
        os.path.basename(new_path),
    )
    return meta
