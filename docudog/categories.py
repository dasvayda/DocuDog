"""Owner-defined business categories (few-shot / forced choice) — not free tags."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def resolve_categories_path(cfg: dict[str, Any], state_path: str) -> str:
    paths = cfg.get("paths") or {}
    raw = str(paths.get("categories_path") or "").strip()
    if raw:
        return os.path.normpath(os.path.expandvars(raw))
    return os.path.join(
        os.path.dirname(os.path.normpath(os.path.expandvars(state_path))),
        "DocuDog_categories.json",
    )


def categories_enabled(cfg: dict[str, Any]) -> bool:
    raw = cfg.get("category_settings")
    if isinstance(raw, dict) and "enabled" in raw:
        return bool(raw.get("enabled"))
    # auto-on if categories file exists and non-empty is too magic — require enabled
    return False


def load_categories(cfg: dict[str, Any], state_path: str) -> dict[str, Any] | None:
    if not categories_enabled(cfg):
        return None
    path = resolve_categories_path(cfg, state_path)
    if not os.path.isfile(path):
        logger.debug("Categories enabled but file missing: %s", path)
        return None
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Categories load failed (%s): %s", path, e)
        return None
    if not isinstance(doc, dict):
        return None
    cats = doc.get("categories")
    if not isinstance(cats, list) or not cats:
        return None
    return doc


def _excerpt_for_category(cat: dict[str, Any], max_chars: int) -> str:
    ex = str(cat.get("sample_excerpt") or "").strip()
    if ex:
        return ex[:max_chars]
    paths = cat.get("sample_paths")
    if not isinstance(paths, list):
        return ""
    for p in paths[:3]:
        fp = os.path.normpath(os.path.expandvars(str(p)))
        if not os.path.isfile(fp):
            continue
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                return f.read(max_chars)
        except OSError:
            continue
    return ""


def prompt_block(doc: dict[str, Any] | None, cfg: dict[str, Any]) -> str:
    if not doc:
        return ""
    cats = doc.get("categories") or []
    if not isinstance(cats, list):
        return ""
    cs = cfg.get("category_settings") if isinstance(cfg.get("category_settings"), dict) else {}
    max_ex = int(cs.get("sample_excerpt_chars", 280))
    mode = str(doc.get("mode") or cs.get("mode") or "single").strip().lower()
    lines = [
        "Business category (choose from the list; do not invent new ids).",
        f'Mode: {"exactly one category_id" if mode != "multi" else "category_ids array (1+)"}.',
        'Add JSON field category_id (string) or category_ids (array of strings). '
        'Use "uncategorized" only if none fit.',
        "Categories:",
    ]
    for cat in cats[:24]:
        if not isinstance(cat, dict):
            continue
        cid = str(cat.get("id") or "").strip()
        if not cid:
            continue
        label = str(cat.get("label") or cid).strip()
        lines.append(f"- id={cid} label={label}")
        ex = _excerpt_for_category(cat, max_ex)
        if ex:
            one = " ".join(ex.split())[:max_ex]
            lines.append(f"  sample: {one}")
        excl = cat.get("exclude_keywords")
        if isinstance(excl, list) and excl:
            lines.append("  exclude if: " + ", ".join(str(x) for x in excl[:6]))
    return "\n".join(lines)


def resolve_from_result(
    result: dict[str, Any],
    doc: dict[str, Any] | None,
    cfg: dict[str, Any],
) -> tuple[list[str], bool]:
    """
    Return (category_ids, needs_review).
    needs_review True when uncategorized or unknown id.
    """
    if not doc:
        return [], False
    allowed = {
        str(c.get("id") or "").strip()
        for c in (doc.get("categories") or [])
        if isinstance(c, dict) and str(c.get("id") or "").strip()
    }
    allowed.add("uncategorized")
    ids: list[str] = []
    raw_multi = result.get("category_ids")
    if isinstance(raw_multi, list):
        ids = [str(x).strip() for x in raw_multi if str(x).strip()]
    elif result.get("category_id") is not None:
        one = str(result.get("category_id") or "").strip()
        if one:
            ids = [one]
    # fallback: tag matching cat:id or exact id
    if not ids:
        for t in result.get("tags") or []:
            s = str(t).strip()
            if s.startswith("cat:"):
                ids.append(s[4:].strip())
            elif s in allowed and s != "uncategorized":
                ids.append(s)
    cleaned: list[str] = []
    for i in ids:
        if i in allowed:
            if i not in cleaned:
                cleaned.append(i)
        else:
            cleaned.append("uncategorized")
    if not cleaned:
        cleaned = ["uncategorized"]
    cs = cfg.get("category_settings") if isinstance(cfg.get("category_settings"), dict) else {}
    mode = str(doc.get("mode") or cs.get("mode") or "single").strip().lower()
    if mode != "multi":
        cleaned = cleaned[:1]
    needs = cleaned == ["uncategorized"] or any(c not in allowed for c in cleaned)
    # unknown already mapped to uncategorized; needs_review if uncategorized
    needs_review = "uncategorized" in cleaned
    return cleaned, needs_review


def label_for(cid: str, doc: dict[str, Any] | None) -> str:
    if not doc:
        return cid
    for c in doc.get("categories") or []:
        if isinstance(c, dict) and str(c.get("id") or "").strip() == cid:
            return str(c.get("label") or cid).strip()
    return cid
