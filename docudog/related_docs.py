"""Related-document candidates after classify (filename key + summary + bundles)."""

from __future__ import annotations

import os
from typing import Any

from .lineage import _summary_jaccard, lineage_group_key


def find_related_paths(
    state: dict[str, Any],
    anchor_path: str,
    anchor_meta: dict[str, Any],
    *,
    max_n: int = 5,
    min_jaccard: float = 0.28,
) -> list[str]:
    """
    Rank other tracked paths related to anchor via:
    same lineage_group_key, summary Jaccard, or context_bundles peer lists.
    """
    files = state.get("files") if isinstance(state.get("files"), dict) else {}
    anchor_norm = os.path.normpath(anchor_path)
    anchor_key = lineage_group_key(os.path.basename(anchor_norm))
    anchor_sum = str(anchor_meta.get("summary") or "")
    scores: dict[str, float] = {}

    for path, meta in files.items():
        if not isinstance(meta, dict):
            continue
        p = os.path.normpath(path)
        if os.path.normcase(p) == os.path.normcase(anchor_norm):
            continue
        score = 0.0
        if lineage_group_key(os.path.basename(p)) == anchor_key:
            score += 1.0
        jac = _summary_jaccard(anchor_sum, str(meta.get("summary") or ""))
        if jac >= min_jaccard:
            score += jac
        if score > 0:
            scores[p] = max(scores.get(p, 0.0), score)

    bundles = state.get("context_bundles")
    if isinstance(bundles, list):
        for b in bundles:
            if not isinstance(b, dict):
                continue
            peers = b.get("related_paths") or b.get("paths") or b.get("members") or []
            if not isinstance(peers, list):
                continue
            peer_norm = [os.path.normpath(str(x)) for x in peers]
            anchor_b = os.path.normpath(str(b.get("anchor_path") or ""))
            if anchor_b:
                peer_norm.append(anchor_b)
            if not any(
                os.path.normcase(x) == os.path.normcase(anchor_norm) for x in peer_norm
            ):
                continue
            for p in peer_norm:
                if os.path.normcase(p) == os.path.normcase(anchor_norm):
                    continue
                if p in files:
                    scores[p] = max(scores.get(p, 0.0), 0.55)

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    return [p for p, _s in ranked[: max(0, max_n)]]
