#!/usr/bin/env python3
"""Rebuild the optional local Zvec index from already classified DocuDog files."""

from __future__ import annotations

import argparse
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from docudog.config_loader import load_app_config
from docudog.mcp_service import McpService
from docudog.router import extract_document_text
from docudog import semantic_index


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-dir", default=ROOT)
    args = parser.parse_args()
    config_dir = os.path.abspath(args.config_dir)
    cfg = load_app_config(config_dir)
    if not semantic_index.enabled(cfg):
        print("semantic_search.enabled is false; enable it in config.yml/config.json first.")
        return 2
    svc = McpService(config_dir)
    state = svc.load_state()
    files = state.get("files") if isinstance(state.get("files"), dict) else {}
    indexed = skipped = failed = 0
    for path, metadata in files.items():
        if not isinstance(metadata, dict):
            continue
        if not os.path.isfile(path):
            semantic_index.remove_file(cfg, path)
            skipped += 1
            continue
        text, reason = extract_document_text(path, cfg)
        if reason or not text:
            semantic_index.remove_file(cfg, path)
            skipped += 1
            continue
        try:
            result = semantic_index.upsert_file(cfg, path=path, text=text, metadata=metadata)
            if result.get("indexed"):
                indexed += 1
            else:
                skipped += 1
        except semantic_index.SemanticIndexError as exc:
            failed += 1
            logging.warning("%s: %s", path, exc)
    print(f"Semantic index rebuild: indexed={indexed} skipped={skipped} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
