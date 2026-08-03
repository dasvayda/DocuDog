"""Skip / blind-spot insights: filename keyword hits on extract skips."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any

_DEFAULT_SENSITIVE_KEYWORDS = (
    "주민등록",
    "졸업증명",
    "계약서",
    "이력서",
    "여권",
    "통장",
    "급여",
    "연봉",
    "신분증",
    "가족관계",
    "개인정보",
    "사업자등록",
    "인감",
    "계좌",
)


def _keywords(cfg: dict[str, Any]) -> list[str]:
    raw = cfg.get("skip_insight_settings")
    if isinstance(raw, dict):
        kw = raw.get("sensitive_filename_keywords")
        if isinstance(kw, list) and kw:
            return [str(x).strip() for x in kw if str(x).strip()]
    return list(_DEFAULT_SENSITIVE_KEYWORDS)


def match_sensitive_filename(cfg: dict[str, Any], path: str) -> str | None:
    """Return first matching keyword in basename, or None."""
    name = os.path.basename(path)
    lower = name.casefold()
    for kw in _keywords(cfg):
        if kw.casefold() in lower:
            return kw
    return None


def record_extract_skip(
    state: dict[str, Any],
    cfg: dict[str, Any],
    path: str,
    reason: str,
) -> dict[str, Any]:
    """
    Update ``state['ops']`` skip counters. Returns a small insight dict for callers.
    """
    ops = state.setdefault("ops", {})
    if not isinstance(ops, dict):
        ops = {}
        state["ops"] = ops
    ops["skip_extract_count"] = int(ops.get("skip_extract_count") or 0) + 1
    by_reason = ops.setdefault("skip_extract_by_reason", {})
    if not isinstance(by_reason, dict):
        by_reason = {}
        ops["skip_extract_by_reason"] = by_reason
    key = (reason or "unknown")[:120]
    by_reason[key] = int(by_reason.get(key) or 0) + 1

    hit = match_sensitive_filename(cfg, path)
    insight: dict[str, Any] = {
        "path": path,
        "reason": reason,
        "sensitive_keyword": hit,
        "utc": datetime.now(timezone.utc).isoformat(),
    }
    if hit:
        ops["skip_extract_sensitive_count"] = int(
            ops.get("skip_extract_sensitive_count") or 0
        ) + 1
        recent = ops.setdefault("skip_extract_sensitive_recent", [])
        if not isinstance(recent, list):
            recent = []
            ops["skip_extract_sensitive_recent"] = recent
        recent.append(
            {
                "path": path,
                "keyword": hit,
                "reason": key,
                "utc": insight["utc"],
            }
        )
        # Keep a short ring buffer
        if len(recent) > 40:
            del recent[:-40]
    return insight


def format_blind_spot_banner(state: dict[str, Any]) -> str:
    """One-line warning for status / report banner (no emoji)."""
    ops = state.get("ops") if isinstance(state.get("ops"), dict) else {}
    total = int(ops.get("skip_extract_count") or 0)
    sens = int(ops.get("skip_extract_sensitive_count") or 0)
    if total <= 0:
        return ""
    if sens > 0:
        return (
            f"미분류(텍스트 추출 미지원 등) {total}건 — "
            f"그중 파일명 개인정보 관련 키워드 {sens}건"
        )
    return f"미분류(텍스트 추출 미지원 등) {total}건"


_BANNER_PATTERN = re.compile(
    r"\r?\n?<!-- docudog-banner:start -->.*?<!-- docudog-banner:end -->\r?\n?",
    re.DOTALL,
)


def banner_markdown_block(state: dict[str, Any]) -> str:
    text = format_blind_spot_banner(state)
    if not text:
        return ""
    return (
        "\n<!-- docudog-banner:start -->\n\n"
        f"> **경고:** {text}\n\n"
        "<!-- docudog-banner:end -->\n"
    )


def upsert_report_banner(report_body: str, state: dict[str, Any]) -> str:
    """Insert or replace the blind-spot banner after the first heading."""
    block = banner_markdown_block(state)
    body = _BANNER_PATTERN.sub("\n", report_body)
    if not block:
        return body
    lines = body.splitlines(keepends=True)
    insert_at = 0
    for i, line in enumerate(lines):
        if line.startswith("# "):
            insert_at = i + 1
            # skip one blank after title if present
            if insert_at < len(lines) and lines[insert_at].strip() == "":
                insert_at += 1
            break
    return "".join(lines[:insert_at]) + block + "".join(lines[insert_at:])
