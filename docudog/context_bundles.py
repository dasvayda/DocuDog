"""Temporal co-occurrence bundles (Context Bundle) — Work IQ–style local heuristic.

Groups files whose watchdog events fall within a configurable window of an anchor
document that finished classification. No web UI; state + Markdown only.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)


def event_buffer_cap(cfg: dict[str, Any]) -> int:
    """Max watchdog (path, time) pairs kept for bundle correlation."""
    raw_ls = cfg.get("lineage_settings") or {}
    if not isinstance(raw_ls, dict):
        raw_ls = {}
    return _settings(raw_ls)["buffer_cap"]


def _norm_path(p: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))


def _settings(ls: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(ls, dict):
        ls = {}
    return {
        "enabled": bool(ls.get("context_bundles_enabled", False)),
        "window_minutes": max(1, min(240, int(ls.get("context_bundle_window_minutes", 30)))),
        "same_folder_only": bool(ls.get("context_bundle_same_folder_only", False)),
        "extra_directories": list(ls.get("context_bundle_extra_directories") or []),
        "max_bundles": max(5, min(500, int(ls.get("context_bundle_max_bundles", 60)))),
        "buffer_cap": max(100, min(10000, int(ls.get("context_bundle_max_event_buffer", 800)))),
    }


def record_fs_event(
    buffer: list[tuple[str, float]],
    path: str,
    t: float,
    cap: int,
) -> None:
    """Append (normalized_path, unix_time); trim head to cap."""
    try:
        np = _norm_path(path)
    except OSError:
        return
    buffer.append((np, float(t)))
    overflow = len(buffer) - cap
    if overflow > 0:
        del buffer[0:overflow]


def _expand_dirs(raw_list: list[Any]) -> list[str]:
    out: list[str] = []
    for item in raw_list:
        s = str(item or "").strip()
        if not s:
            continue
        try:
            out.append(_norm_path(os.path.expandvars(s)))
        except OSError:
            continue
    return out


def _related_paths(
    anchor_norm: str,
    event_ts: float,
    snapshot: list[tuple[str, float]],
    window_sec: float,
    same_folder_only: bool,
    extra_roots_norm: list[str],
) -> list[str]:
    anchor_dir = os.path.dirname(anchor_norm)
    seen: set[str] = set()
    out: list[str] = []
    for path, t in snapshot:
        if path == anchor_norm:
            continue
        if abs(float(t) - float(event_ts)) > window_sec:
            continue
        pdir = os.path.dirname(path)
        in_same = pdir == anchor_dir
        under_extra = any(
            path == r or path.startswith(r + os.sep)
            for r in extra_roots_norm
        )
        if same_folder_only:
            if not in_same:
                continue
        else:
            if extra_roots_norm:
                if not (in_same or under_extra):
                    continue
            else:
                if not in_same:
                    continue
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def update_bundles_after_analysis(
    cfg: dict[str, Any],
    state: dict[str, Any],
    anchor_path: str,
    event_ts: float,
    snapshot: list[tuple[str, float]],
    persist: Callable[[], None],
) -> None:
    """After successful classify + state row written, maybe append a context bundle."""
    raw_ls = cfg.get("lineage_settings") or {}
    if not isinstance(raw_ls, dict):
        raw_ls = {}
    s = _settings(raw_ls)
    if not s["enabled"]:
        return
    try:
        anchor_norm = _norm_path(anchor_path)
    except OSError:
        return

    window_sec = float(s["window_minutes"]) * 60.0
    extra_roots = _expand_dirs(s["extra_directories"])
    related = _related_paths(
        anchor_norm,
        event_ts,
        snapshot,
        window_sec,
        s["same_folder_only"],
        extra_roots,
    )
    if not related:
        logger.debug(
            "Context bundle: no related files within %s min of anchor %s",
            s["window_minutes"],
            os.path.basename(anchor_norm),
        )
        return

    now = datetime.now(timezone.utc)
    sig = f"{anchor_norm}|{event_ts:.3f}|{','.join(related)}".encode("utf-8", errors="replace")
    bundle_id = hashlib.sha256(sig).hexdigest()[:12]
    bundle = {
        "bundle_id": bundle_id,
        "anchor_path": anchor_norm,
        "anchor_event_utc": datetime.fromtimestamp(event_ts, tz=timezone.utc).isoformat(),
        "related_paths": related,
        "window_minutes": s["window_minutes"],
        "updated_utc": now.isoformat(),
    }

    bundles = state.setdefault("context_bundles", [])
    if not isinstance(bundles, list):
        bundles = []
        state["context_bundles"] = bundles
    bundles.insert(0, bundle)
    overflow = len(bundles) - s["max_bundles"]
    if overflow > 0:
        del bundles[s["max_bundles"] :]

    persist()
    logger.info(
        "Context bundle %s: anchor=%s + %d related (within %s min)",
        bundle_id,
        os.path.basename(anchor_norm),
        len(related),
        s["window_minutes"],
    )
