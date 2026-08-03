#!/usr/bin/env python3
"""Search DocuDog_state.json by security level, tags, path/summary keywords.

Not full-text of original files — governance corpus over already-classified metadata.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from docudog.config_loader import load_app_config  # noqa: E402
from docudog.security_labels import format_security_level  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Search classified DocuDog state corpus.")
    parser.add_argument("--config-dir", default=ROOT)
    parser.add_argument("--level", default="", help="P1|P2|P3|P4 (optional)")
    parser.add_argument("--tag", default="", help="Tag substring (case-insensitive)")
    parser.add_argument(
        "--query",
        default="",
        help="Regex or plain substring over path+summary+tags",
    )
    parser.add_argument("--regex", action="store_true", help="Treat --query as regex")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    cfg = load_app_config(args.config_dir)
    state_path = os.path.normpath(
        os.path.expandvars(
            str(
                (cfg.get("paths") or {}).get("state_path")
                or "%USERPROFILE%/Documents/DocuDog_state.json"
            )
        )
    )
    if not os.path.isfile(state_path):
        print(f"search_corpus: state missing: {state_path}", file=sys.stderr)
        return 1
    with open(state_path, encoding="utf-8") as f:
        state = json.load(f)
    files = state.get("files") if isinstance(state.get("files"), dict) else {}

    level = args.level.strip().upper()
    tag_q = args.tag.strip().casefold()
    q = args.query.strip()
    cre: re.Pattern[str] | None = None
    if q and args.regex:
        try:
            cre = re.compile(q, re.I)
        except re.error as e:
            print(f"search_corpus: bad regex: {e}", file=sys.stderr)
            return 1

    hits: list[tuple[str, dict]] = []
    for path, meta in files.items():
        if not isinstance(meta, dict):
            continue
        sec = str(meta.get("security_level") or "").upper()
        if level and sec != level:
            continue
        tags = meta.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        tag_join = ", ".join(str(t) for t in tags)
        if tag_q and tag_q not in tag_join.casefold():
            continue
        blob = f"{path}\n{meta.get('summary') or ''}\n{tag_join}"
        if q:
            if cre is not None:
                if not cre.search(blob):
                    continue
            elif q.casefold() not in blob.casefold():
                continue
        hits.append((path, meta))

    hits.sort(key=lambda pm: str(pm[1].get("last_analyzed_utc") or ""), reverse=True)
    limit = max(1, int(args.limit))
    print(f"search_corpus: {len(hits)} match(es) (showing {min(limit, len(hits))})")
    for path, meta in hits[:limit]:
        sec = str(meta.get("security_level") or "")
        tags = meta.get("tags") or []
        print(
            f"- {format_security_level(sec, cfg)} | tags={tags} | "
            f"{path}"
        )
        summ = str(meta.get("summary") or "").strip()
        if summ:
            print(f"  summary: {summ[:160]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
