#!/usr/bin/env python3
"""Apply DocuDog_tag_overrides.json to DocuDog_state.json without re-running inference."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from docudog import artifact_home  # noqa: E402
from docudog import lineage  # noqa: E402
from docudog import owner_tags  # noqa: E402
from main import load_state, save_state_atomic  # noqa: E402


def main() -> int:
    cfg = load_app_config(ROOT)
    state_path = artifact_home.resolve_state_path(cfg)
    report_path = artifact_home.resolve_report_path(cfg)

    state = load_state(state_path)
    odoc = owner_tags.load_tag_overrides(cfg, state_path)
    files = state.setdefault("files", {})
    updated = 0

    for norm_path, meta in list(files.items()):
        if not isinstance(meta, dict):
            continue
        model_tags_raw = meta.get("model_tags")
        if model_tags_raw is None:
            model_tags_raw = meta.get("tags") or []
        if isinstance(model_tags_raw, str):
            model_tags = [model_tags_raw]
        else:
            model_tags = [str(t) for t in model_tags_raw if str(t).strip()]
        model_sec = str(
            meta.get("model_security_level") or meta.get("security_level") or "P4"
        )
        tags, sec, applied = owner_tags.merge_owner_tags(
            norm_path, model_tags, model_sec, odoc
        )
        if applied:
            meta["tags"] = tags
            meta["security_level"] = sec
            meta["owner_override"] = True
            updated += 1

    save_state_atomic(state_path, state)
    try:
        lineage.regenerate_if_enabled(cfg, state, report_path)
    except Exception as e:
        print("sync_tag_overrides: lineage regenerate failed:", e, flush=True)
        return 1

    print(
        f"sync_tag_overrides: state={state_path} overrides={owner_tags.resolve_tag_overrides_path(cfg, state_path)} updated={updated}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
