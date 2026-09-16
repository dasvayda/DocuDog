"""Freshness signals for copilots: disk mtime vs classification, latest vs superseded.

Two questions a chat client cannot answer from `state` alone:

1. "Is this classification still valid?" — a NAS/shared file may have been
   overwritten after DocuDog analyzed it (`stale_classification`).
2. "Which copy should I quote?" — `제안서_초안.docx` and `제안서_최종_진짜.docx`
   both match a query, so the model needs `is_latest` / `superseded_by`.

Read-only: nothing here renames, moves, or rewrites user documents.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from .lineage import _normalize_stem_similarity

logger = logging.getLogger(__name__)

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

# Filename hints. Korean office habits put the decision in the name, not the mtime.
_FINAL_TOKENS = ("최종", "확정", "진짜", "완성", "제출", "final", "release", "approved")
_DRAFT_TOKENS = (
    "초안",
    "임시",
    "이전",
    "구버전",
    "복사본",
    "backup",
    "copy",
    "draft",
    "old",
    "temp",
    "wip",
)
_RE_VERSION = re.compile(r"(?:^|[_\s.\-])(?:v|ver|version|r|rev)[.\s_-]?(\d{1,3})\b", re.I)
_RE_PAREN_NUM = re.compile(r"\((\d{1,3})\)\s*$")

# Trailing decoration stripped so `제안서_v1` and `제안서_최종_진짜` share one group.
_GROUP_TOKENS = _FINAL_TOKENS + _DRAFT_TOKENS + (
    "최종본",
    "수정",
    "수정본",
    "완료",
    "편집",
    "본안",
    "complete",
    "done",
    "edit",
    "revised",
)
_RE_TRAILING_TOKEN = re.compile(
    r"[_\s.\-]*(?:" + "|".join(re.escape(t) for t in _GROUP_TOKENS) + r")\d*\s*$",
    re.I,
)
_RE_TRAILING_VER = re.compile(r"[_\s.\-]*(?:v|ver|version|r|rev)[.\s_\-]?\d+\s*$", re.I)
_RE_TRAILING_NUM = re.compile(r"[_\s.\-]+\d{1,4}\s*$")
_RE_COPY_PAREN = re.compile(r"\s*\(\d+\)\s*$")


def settings(config: dict[str, Any] | None) -> dict[str, Any]:
    raw = (config or {}).get("freshness_settings")
    return raw if isinstance(raw, dict) else {}


def enabled(config: dict[str, Any] | None) -> bool:
    return bool(settings(config).get("enabled", True))


def stale_skew_seconds(config: dict[str, Any] | None) -> float:
    raw = settings(config).get("stale_skew_seconds", 60)
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 60.0


def parse_utc(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def file_mtime_utc(path: str) -> str:
    """Disk modification time as UTC ISO, or empty when unreadable."""
    try:
        stamp = os.path.getmtime(path)
    except OSError:
        return ""
    try:
        return datetime.fromtimestamp(stamp, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return ""


def staleness(
    path: str,
    meta: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare on-disk mtime with `last_analyzed_utc` (shared folders, NAS)."""
    exists = os.path.isfile(path)
    mtime_iso = file_mtime_utc(path) if exists else ""
    out: dict[str, Any] = {
        "file_exists": exists,
        "file_mtime_utc": mtime_iso,
        "stale_classification": False,
        "stale_reason": "",
    }
    if not enabled(config):
        return out
    if not exists:
        out["stale_reason"] = "이 경로에 파일이 없음 (이동·삭제 가능; 분류본은 과거 스냅샷)"
        return out
    modified = parse_utc(mtime_iso)
    analyzed = parse_utc(str(meta.get("last_analyzed_utc") or ""))
    if modified is None or analyzed is None:
        return out
    if (modified - analyzed).total_seconds() > stale_skew_seconds(config):
        out["stale_classification"] = True
        out["stale_reason"] = (
            "분석 이후 파일이 수정됨 — 재분류 대기 중 (요약·등급이 낡을 수 있음)"
        )
    return out


def version_number(basename: str) -> int:
    stem = os.path.splitext(basename)[0]
    best = 0
    for match in _RE_VERSION.finditer(stem):
        try:
            best = max(best, int(match.group(1)))
        except ValueError:
            continue
    paren = _RE_PAREN_NUM.search(stem)
    if paren:
        try:
            best = max(best, int(paren.group(1)))
        except ValueError:
            pass
    return best


def name_bonus(basename: str) -> int:
    """Positive when the filename claims to be final, negative for draft/backup."""
    folded = basename.casefold()
    score = 0
    for token in _FINAL_TOKENS:
        if token in folded:
            score += 1
    for token in _DRAFT_TOKENS:
        if token in folded:
            score -= 1
    return score


def group_key(path: str) -> str:
    """Same logical document across `_v1` / `_최종_진짜` style filename variants."""
    stem, ext = os.path.splitext(os.path.basename(path))
    base = _normalize_stem_similarity(stem)
    stripped = base
    for _ in range(8):
        prev = stripped
        stripped = _RE_COPY_PAREN.sub("", stripped)
        stripped = _RE_TRAILING_VER.sub("", stripped)
        stripped = _RE_TRAILING_TOKEN.sub("", stripped)
        stripped = _RE_TRAILING_NUM.sub("", stripped)
        stripped = stripped.strip(" _.-")
        if stripped == prev:
            break
    if not stripped:
        stripped = base
    stripped = re.sub(r"[_\s.\-]+", "_", stripped).strip("_")
    return f"{stripped.lower()}{ext.lower()}"


def effective_utc(path: str, meta: dict[str, Any]) -> datetime:
    """Newest of disk mtime and classification time (shared folders win)."""
    candidates = [
        parse_utc(file_mtime_utc(path)),
        parse_utc(str(meta.get("last_analyzed_utc") or "")),
        parse_utc(str(meta.get("last_checked_utc") or "")),
    ]
    stamps = [c for c in candidates if c is not None]
    return max(stamps) if stamps else _EPOCH


def _sort_key(path: str, meta: dict[str, Any]) -> tuple[datetime, int, int, str]:
    basename = os.path.basename(path)
    return (
        effective_utc(path, meta),
        name_bonus(basename),
        version_number(basename),
        basename.casefold(),
    )


def _why_latest(path: str, meta: dict[str, Any], runner_up: str) -> str:
    basename = os.path.basename(path)
    reasons: list[str] = []
    if name_bonus(basename) > 0:
        reasons.append("파일명에 최종 표시")
    version = version_number(basename)
    if version:
        reasons.append(f"버전 번호 v{version}")
    if file_mtime_utc(path):
        reasons.append("디스크 수정 시각이 가장 최신")
    elif meta.get("last_analyzed_utc"):
        reasons.append("분석 시각이 가장 최신")
    if not reasons:
        reasons.append("같은 계열에서 가장 최근 항목")
    text = ", ".join(reasons)
    if runner_up:
        text += f" (직전: {os.path.basename(runner_up)})"
    return text


def _merge_version_threads(
    state: dict[str, Any],
    key_of: dict[str, str],
) -> dict[str, str]:
    """Let explicit version threads override filename-only grouping."""
    alias: dict[str, str] = {}

    def resolve(key: str) -> str:
        seen: set[str] = set()
        while key in alias and key not in seen:
            seen.add(key)
            key = alias[key]
        return key

    threads = state.get("threads")
    if not isinstance(threads, list):
        return alias
    for thread in threads:
        if not isinstance(thread, dict):
            continue
        # Conversation/mixed threads group peers, not versions of one document.
        if str(thread.get("kind") or "") != "version":
            continue
        keys: list[str] = []
        for member in thread.get("members") or []:
            if not isinstance(member, dict):
                continue
            member_path = str(member.get("path") or "")
            key = key_of.get(os.path.normcase(member_path))
            if key:
                keys.append(resolve(key))
        unique = list(dict.fromkeys(keys))
        if len(unique) < 2:
            continue
        primary = unique[0]
        for other in unique[1:]:
            alias[other] = primary
    return alias


def build_latest_map(
    state: dict[str, Any],
    config: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Map normcase path -> {is_latest, superseded_by, latest_reason, group_size}."""
    files = state.get("files") if isinstance(state.get("files"), dict) else {}
    rows: list[tuple[str, dict[str, Any]]] = [
        (path, meta) for path, meta in files.items() if isinstance(meta, dict)
    ]
    if not rows:
        return {}

    key_of = {os.path.normcase(path): group_key(path) for path, _meta in rows}
    alias = _merge_version_threads(state, key_of)

    def final_key(path: str) -> str:
        key = key_of.get(os.path.normcase(path), group_key(path))
        seen: set[str] = set()
        while key in alias and key not in seen:
            seen.add(key)
            key = alias[key]
        return key

    groups: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for path, meta in rows:
        groups.setdefault(final_key(path), []).append((path, meta))

    out: dict[str, dict[str, Any]] = {}
    for members in groups.values():
        if len(members) == 1:
            path, _meta = members[0]
            out[os.path.normcase(path)] = {
                "is_latest": True,
                "superseded_by": "",
                "latest_reason": "같은 계열의 다른 버전이 state에 없음",
                "group_size": 1,
            }
            continue
        ordered = sorted(members, key=lambda pm: _sort_key(pm[0], pm[1]), reverse=True)
        latest_path, latest_meta = ordered[0]
        runner_up = ordered[1][0] if len(ordered) > 1 else ""
        reason = _why_latest(latest_path, latest_meta, runner_up)
        for index, (path, _meta) in enumerate(ordered):
            if index == 0:
                out[os.path.normcase(path)] = {
                    "is_latest": True,
                    "superseded_by": "",
                    "latest_reason": reason,
                    "group_size": len(ordered),
                }
            else:
                out[os.path.normcase(path)] = {
                    "is_latest": False,
                    "superseded_by": latest_path,
                    "latest_reason": (
                        f"더 최신본 `{os.path.basename(latest_path)}` 이 있음 — {reason}"
                    ),
                    "group_size": len(ordered),
                }
    return out


def latest_info(
    path: str,
    latest_map: dict[str, dict[str, Any]] | None,
) -> dict[str, Any]:
    if not latest_map:
        return {}
    return dict(latest_map.get(os.path.normcase(path)) or {})


def previous_versions(
    state: dict[str, Any],
    latest_path: str,
    latest_map: dict[str, dict[str, Any]],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Older members of the same group, newest first (summary only)."""
    files = state.get("files") if isinstance(state.get("files"), dict) else {}
    target = os.path.normcase(latest_path)
    rows: list[tuple[str, dict[str, Any]]] = []
    for path, meta in files.items():
        if not isinstance(meta, dict):
            continue
        info = latest_map.get(os.path.normcase(path)) or {}
        if info.get("is_latest"):
            continue
        if os.path.normcase(str(info.get("superseded_by") or "")) != target:
            continue
        rows.append((path, meta))
    rows.sort(key=lambda pm: _sort_key(pm[0], pm[1]), reverse=True)
    out: list[dict[str, Any]] = []
    for path, meta in rows[: max(1, limit)]:
        out.append(
            {
                "path": path,
                "basename": os.path.basename(path),
                "last_analyzed_utc": str(meta.get("last_analyzed_utc") or ""),
                "summary": str(meta.get("summary") or "")[:200],
            }
        )
    return out
