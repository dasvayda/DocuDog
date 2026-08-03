"""Write DocuDog_last_classify.json after a successful classification."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def resolve_last_classify_path(cfg: dict[str, Any], report_path: str) -> str:
    paths = cfg.get("paths") or {}
    raw = str(paths.get("last_classify_path") or "").strip()
    if raw:
        return os.path.normpath(os.path.expandvars(raw))
    return os.path.join(
        os.path.dirname(os.path.normpath(os.path.expandvars(report_path))),
        "DocuDog_last_classify.json",
    )


def write_last_classify(
    cfg: dict[str, Any],
    report_path: str,
    *,
    path: str,
    security_level: str,
    tags: list[str],
    summary: str,
    inference_source: str,
    file_hash: str = "",
    when: datetime | None = None,
    category_ids: list[str] | None = None,
    change_summary: str = "",
) -> str | None:
    out = resolve_last_classify_path(cfg, report_path)
    payload = {
        "path": path,
        "basename": os.path.basename(path),
        "security_level": security_level,
        "tags": tags,
        "summary": summary,
        "inference_source": inference_source,
        "sha256": file_hash,
        "utc": (when or datetime.now(timezone.utc)).isoformat(),
        "category_ids": list(category_ids or []),
        "change_summary": change_summary or "",
    }
    try:
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        tmp = out + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, out)
    except OSError as e:
        logger.warning("last_classify write failed (%s): %s", out, e)
        return None
    return out
