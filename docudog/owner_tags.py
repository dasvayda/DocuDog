"""Local file owner tag/security overrides (JSON sidecar, no network)."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

_SECURITY_LEVEL_RE = re.compile(r"^P[1-4]$")


def resolve_tag_overrides_path(cfg: dict[str, Any], state_path: str) -> str:
    raw = str((cfg.get("paths") or {}).get("tag_overrides_path") or "").strip()
    if raw:
        return os.path.normpath(os.path.expandvars(raw))
    base = os.path.dirname(os.path.normpath(os.path.expandvars(state_path)))
    return os.path.join(base, "DocuDog_tag_overrides.json")


def load_tag_overrides(cfg: dict[str, Any], state_path: str) -> dict[str, Any]:
    path = resolve_tag_overrides_path(cfg, state_path)
    if not os.path.isfile(path):
        return {"version": 1, "entries": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("tag_overrides: could not load %s (%s)", path, e)
        return {"version": 1, "entries": {}}
    if not isinstance(data, dict):
        return {"version": 1, "entries": {}}
    entries = data.get("entries")
    if not isinstance(entries, dict):
        entries = {}
    return {"version": int(data.get("version", 1)), "entries": entries}


def _entry_for_path(norm_path: str, entries: dict[str, Any]) -> dict[str, Any] | None:
    if norm_path in entries:
        raw = entries[norm_path]
        return raw if isinstance(raw, dict) else None
    target = os.path.normcase(norm_path)
    for k, v in entries.items():
        try:
            if os.path.normcase(os.path.normpath(os.path.expandvars(str(k)))) == target:
                return v if isinstance(v, dict) else None
        except OSError:
            continue
    return None


def merge_owner_tags(
    norm_path: str,
    model_tags: list[str],
    model_security_level: str,
    overrides_doc: dict[str, Any],
) -> tuple[list[str], str, bool]:
    """
    Owner entries win on tags and/or security when provided.

    Returns (effective_tags, effective_security, owner_applied).
    """
    entries = overrides_doc.get("entries") or {}
    if not isinstance(entries, dict):
        return model_tags, model_security_level, False
    raw = _entry_for_path(norm_path, entries)
    if not raw:
        return model_tags, model_security_level, False

    tags = list(model_tags)
    sec = model_security_level
    owner_applied = False

    if raw.get("tags") is not None:
        t = raw["tags"]
        if isinstance(t, str):
            t = [t]
        if isinstance(t, list):
            nt = [str(x).strip() for x in t if str(x).strip()]
            if nt:
                tags = nt
                owner_applied = True

    if raw.get("security_level") is not None:
        s = str(raw["security_level"]).strip()
        if _SECURITY_LEVEL_RE.match(s):
            sec = s
            owner_applied = True

    return tags, sec, owner_applied
