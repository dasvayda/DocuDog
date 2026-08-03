"""Periodic document cadence checks (absence / miss detection)."""

from __future__ import annotations

import fnmatch
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def cadence_enabled(cfg: dict[str, Any]) -> bool:
    raw = cfg.get("cadence_settings")
    if not isinstance(raw, dict):
        return False
    return bool(raw.get("enabled", False))


def _in_period(
    iso_utc: str,
    *,
    cadence: str,
    now: datetime,
    due_weekday: int | None,
    due_day: int | None,
) -> bool:
    """True if iso_utc falls in the current cadence window (UTC)."""
    if not iso_utc:
        return False
    try:
        ts = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ts = ts.astimezone(timezone.utc)
    except ValueError:
        return False
    now_u = now.astimezone(timezone.utc)
    c = (cadence or "weekly").strip().lower()
    if c == "monthly":
        if due_day is not None:
            # window: from due_day this month (or previous) — simplify: same calendar month
            return ts.year == now_u.year and ts.month == now_u.month
        return ts.year == now_u.year and ts.month == now_u.month
    # weekly: ISO week
    return ts.isocalendar()[:2] == now_u.isocalendar()[:2]


def _name_matches(pattern: str, name: str) -> bool:
    pat = (pattern or "").strip()
    if not pat:
        return False
    if any(ch in pat for ch in "*?[]"):
        return fnmatch.fnmatch(name.casefold(), pat.casefold())
    try:
        return re.search(pat, name, flags=re.I) is not None
    except re.error:
        return pat.casefold() in name.casefold()


def evaluate_cadence(
    cfg: dict[str, Any],
    state: dict[str, Any],
    *,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """
    Return list of rule results:
    {id, label, status: miss|ok, latest_path?, message}
    """
    if not cadence_enabled(cfg):
        return []
    raw = cfg.get("cadence_settings") or {}
    rules = raw.get("rules") if isinstance(raw, dict) else None
    if not isinstance(rules, list):
        return []
    now_u = now or datetime.now(timezone.utc)
    files = state.get("files") if isinstance(state.get("files"), dict) else {}
    results: list[dict[str, Any]] = []

    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rid = str(rule.get("id") or "rule").strip()
        label = str(rule.get("label") or rid).strip()
        pattern = str(rule.get("pattern") or "").strip()
        cadence = str(rule.get("cadence") or "weekly").strip().lower()
        due_weekday = rule.get("due_weekday")
        due_day = rule.get("due_day")
        try:
            due_weekday_i = int(due_weekday) if due_weekday is not None else None
        except (TypeError, ValueError):
            due_weekday_i = None
        try:
            due_day_i = int(due_day) if due_day is not None else None
        except (TypeError, ValueError):
            due_day_i = None
        sub = str(rule.get("watch_subdir") or "").strip()

        candidates: list[tuple[str, dict[str, Any]]] = []
        for path, meta in files.items():
            if not isinstance(meta, dict):
                continue
            name = os.path.basename(path)
            if not _name_matches(pattern, name):
                continue
            if sub:
                if sub.replace("\\", "/") not in path.replace("\\", "/"):
                    continue
            iso = str(meta.get("last_analyzed_utc") or meta.get("last_checked_utc") or "")
            if _in_period(
                iso,
                cadence=cadence,
                now=now_u,
                due_weekday=due_weekday_i,
                due_day=due_day_i,
            ):
                candidates.append((path, meta))

        if candidates:
            latest = max(
                candidates,
                key=lambda pm: str(
                    pm[1].get("last_analyzed_utc") or pm[1].get("last_checked_utc") or ""
                ),
            )
            results.append(
                {
                    "id": rid,
                    "label": label,
                    "status": "ok",
                    "latest_path": latest[0],
                    "message": f"{label}: 이번 주기 검출 — `{os.path.basename(latest[0])}`",
                }
            )
        else:
            results.append(
                {
                    "id": rid,
                    "label": label,
                    "status": "miss",
                    "latest_path": "",
                    "message": f"{label}: 이번 주기 미검출 (pattern={pattern})",
                }
            )
    return results


def format_cadence_status_md(results: list[dict[str, Any]]) -> str:
    if not results:
        return ""
    lines = ["## 주기 문서 (cadence)\n\n"]
    for r in results:
        mark = "MISS" if r.get("status") == "miss" else "OK"
        lines.append(f"- **[{mark}]** {r.get('message')}\n")
    lines.append("\n")
    return "".join(lines)


def log_cadence_misses(
    cfg: dict[str, Any],
    report_path: str,
    results: list[dict[str, Any]],
) -> None:
    from . import activity

    for r in results:
        if r.get("status") != "miss":
            continue
        activity.append_activity(
            cfg,
            report_path,
            "cadence_miss",
            str(r.get("message") or r.get("id")),
        )
