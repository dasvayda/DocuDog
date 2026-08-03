"""Security level display labels (human-readable + P-code)."""

from __future__ import annotations

from typing import Any

_DEFAULT_LABELS = {
    "P1": "매우 민감",
    "P2": "민감",
    "P3": "내부",
    "P4": "일반",
}


def security_level_labels(cfg: dict[str, Any] | None) -> dict[str, str]:
    out = dict(_DEFAULT_LABELS)
    if not isinstance(cfg, dict):
        return out
    raw = cfg.get("security_level_labels")
    if isinstance(raw, dict):
        for k, v in raw.items():
            key = str(k).strip().upper()
            if key and str(v).strip():
                out[key] = str(v).strip()
    return out


def format_security_level(level: str, cfg: dict[str, Any] | None = None) -> str:
    """e.g. ``매우 민감 (P1)``; unknown codes return as-is."""
    code = str(level or "").strip().upper()
    if not code:
        return ""
    labels = security_level_labels(cfg)
    label = labels.get(code)
    if label:
        return f"{label} ({code})"
    return code
