#!/usr/bin/env python3
"""Regression smoke: fixture copy -> classify -> hash skip -> edit -> reclassify.

Uses mock inference so CI and fresh clones need no LLM server.
Writes state/report under a temp directory (does not touch user Documents).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from docudog import single_file  # noqa: E402
from main import load_config, load_state, save_state_atomic  # noqa: E402

FIXTURE = os.path.join(ROOT, "fixtures", "sample_internal_memo.md")


def _fail(msg: str) -> int:
    print(f"regression_smoke: FAIL — {msg}", file=sys.stderr)
    return 1


def main() -> int:
    if not os.path.isfile(FIXTURE):
        return _fail(f"fixture missing: {FIXTURE}")

    cfg_path = os.path.join(ROOT, "config.json")
    if not os.path.isfile(cfg_path):
        cfg_path = os.path.join(ROOT, "config.example.json")
    with open(cfg_path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("model", {})["use_mock"] = True
    cfg["model"]["litert_lm_bundle_path"] = ""
    cfg["model"]["enable_litert_lm"] = False
    cfg["model"]["enable_lm_studio"] = False
    cfg.setdefault("lineage_settings", {})["enabled"] = False

    tmp = tempfile.mkdtemp(prefix="docudog_regression_")
    try:
        state_path = os.path.join(tmp, "DocuDog_state.json")
        report_path = os.path.join(tmp, "classification_report.md")
        work_copy = os.path.join(tmp, "sample_internal_memo.md")
        shutil.copy2(FIXTURE, work_copy)

        state = load_state(state_path)

        def persist() -> None:
            save_state_atomic(state_path, state)

        r1 = single_file.process_single_path(
            cfg, state, work_copy, report_path, state_path, persist, update_lineage=False
        )
        if r1.outcome != single_file.SingleFileOutcome.ANALYZED:
            return _fail(f"first classify expected analyzed, got {r1.outcome.value}")

        r2 = single_file.process_single_path(
            cfg, state, work_copy, report_path, state_path, persist, update_lineage=False
        )
        if r2.outcome != single_file.SingleFileOutcome.SKIPPED_UNCHANGED:
            return _fail(f"second classify expected skipped_unchanged, got {r2.outcome.value}")

        with open(work_copy, "a", encoding="utf-8") as f:
            f.write("\n\nRevision note appended for regression smoke.\n")

        r3 = single_file.process_single_path(
            cfg, state, work_copy, report_path, state_path, persist, update_lineage=False
        )
        if r3.outcome != single_file.SingleFileOutcome.ANALYZED:
            return _fail(f"third classify after edit expected analyzed, got {r3.outcome.value}")
        if r3.file_hash == r1.file_hash:
            return _fail("hash should change after edit")

        with open(report_path, encoding="utf-8") as f:
            report_body = f.read()
        if report_body.count("|") < 4:
            return _fail("report looks empty")

        print("regression_smoke: OK")
        print(f"  fixture: {FIXTURE}")
        print(f"  temp dir: {tmp}")
        print(f"  first:  {r1.outcome.value} tags={r1.tags}")
        print(f"  second: {r2.outcome.value}")
        print(f"  third:  {r3.outcome.value} new_sha256={r3.file_hash[:16]}...")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
