#!/usr/bin/env python3
"""CLI/test helper: compose a third document from classified file_ids or paths."""

from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from docudog import artifact_home, compose  # noqa: E402
from docudog.config_loader import load_app_config  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="Compose a briefing or handover markdown.")
    p.add_argument("--config-dir", default=ROOT, help="Directory with config.json")
    p.add_argument("--ids", default="", help="Comma-separated file_id values")
    p.add_argument("--paths", default="", help="Comma-separated absolute paths")
    p.add_argument("--thread-id", default="", help="Use members of this thread id")
    p.add_argument("--kind", default="brief", choices=("brief", "handover"))
    p.add_argument("--intent", default="")
    p.add_argument("--format", default="md,html", help="md, html, docx (comma)")
    p.add_argument("--stdout", action="store_true", help="Print markdown, still write files unless --preview")
    p.add_argument("--preview", action="store_true", help="Do not write files; print markdown")
    args = p.parse_args()
    cfg = load_app_config(os.path.abspath(args.config_dir))
    state_path = artifact_home.resolve_state_path(cfg)
    if os.path.isfile(state_path):
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    else:
        state = {"version": 1, "files": {}}
    ids = [x.strip() for x in args.ids.split(",") if x.strip()]
    paths = [x.strip() for x in args.paths.split(",") if x.strip()]
    formats = [x.strip() for x in args.format.split(",") if x.strip()]
    if args.preview:
        sources, err = compose.resolve_sources(
            cfg, state, selected_ids=ids, selected_paths=paths
        )
        if err:
            print(err, file=sys.stderr)
            return 2
        if args.thread_id and not sources:
            ids = compose.file_ids_for_thread(state, args.thread_id)
            sources, err = compose.resolve_sources(cfg, state, selected_ids=ids)
            if err:
                print(err, file=sys.stderr)
                return 2
        md = compose.compose_markdown(
            cfg, state, kind=args.kind, intent=args.intent, sources=sources
        )
        print(md)
        return 0
    result = compose.compose(
        cfg,
        state,
        kind=args.kind,
        intent=args.intent,
        file_ids_selected=ids,
        paths_selected=paths,
        thread_id=args.thread_id,
        formats=formats,
        report_path=artifact_home.resolve_report_path(cfg),
    )
    if not result.get("ok"):
        print(result.get("error") or "compose failed", file=sys.stderr)
        return 2
    if args.stdout:
        print(result.get("markdown") or "")
    for key, path in (result.get("paths") or {}).items():
        print(f"{key}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
