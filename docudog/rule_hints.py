"""Keyword/regex rule hints + optional security floor (hybrid with LLM)."""

from __future__ import annotations

import re
from typing import Any


_LEVEL_RANK = {"P4": 0, "P3": 1, "P2": 2, "P1": 3}


def _rank(level: str) -> int:
    return _LEVEL_RANK.get(str(level or "").strip().upper(), -1)


def _higher(a: str, b: str) -> str:
    """Return the more sensitive of two P-levels (P1 > P4)."""
    aa = str(a or "").strip().upper()
    bb = str(b or "").strip().upper()
    if _rank(aa) >= _rank(bb):
        return aa if aa in _LEVEL_RANK else bb
    return bb if bb in _LEVEL_RANK else aa


def rules_enabled(cfg: dict[str, Any]) -> bool:
    raw = cfg.get("rule_settings")
    if not isinstance(raw, dict):
        return False
    return bool(raw.get("enabled", False))


def match_rules(text: str, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Return list of matched rule dicts with id/hint/min_security_level."""
    if not rules_enabled(cfg):
        return []
    raw = cfg.get("rule_settings") or {}
    rules = raw.get("rules") if isinstance(raw, dict) else None
    if not isinstance(rules, list):
        return []
    blob = text or ""
    hits: list[dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        rid = str(rule.get("id") or "").strip() or "rule"
        hint = str(rule.get("hint") or "").strip()
        floor = str(rule.get("min_security_level") or "").strip().upper()
        matched = False
        pat = rule.get("pattern")
        if pat:
            try:
                if re.search(str(pat), blob, flags=re.IGNORECASE | re.MULTILINE):
                    matched = True
            except re.error:
                continue
        kws = rule.get("keywords")
        if not matched and isinstance(kws, list):
            low = blob.casefold()
            for kw in kws:
                s = str(kw).strip()
                if s and s.casefold() in low:
                    matched = True
                    break
        if matched:
            hits.append(
                {
                    "id": rid,
                    "hint": hint or rid,
                    "min_security_level": floor if floor in _LEVEL_RANK else "",
                }
            )
    return hits


def prompt_hint_block(hits: list[dict[str, Any]]) -> str:
    if not hits:
        return ""
    parts = []
    for h in hits[:8]:
        floor = h.get("min_security_level") or ""
        extra = f" (prefer >= {floor})" if floor else ""
        parts.append(f"- {h.get('id')}: {h.get('hint')}{extra}")
    return (
        "Local rule hints (raise sensitivity when clearly applicable; still output valid JSON):\n"
        + "\n".join(parts)
    )


def apply_security_floor(
    model_level: str,
    hits: list[dict[str, Any]],
) -> tuple[str, str | None]:
    """
    Raise model_level to the max min_security_level among hits.
    Returns (effective_level, floor_applied_or_None).
    """
    floor: str | None = None
    for h in hits:
        f = str(h.get("min_security_level") or "").upper()
        if f in _LEVEL_RANK:
            floor = f if floor is None else _higher(floor, f)
    if not floor:
        return str(model_level or "").strip().upper() or "P4", None
    effective = _higher(model_level, floor)
    if effective == str(model_level or "").strip().upper():
        return effective, None
    return effective, floor
