#!/usr/bin/env python3
"""Lightweight governance lint over DocuDog_state.json (+ optional audit log).

Read-only on original documents. Writes DocuDog_lint_report.md next to the report.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from docudog.config_loader import load_app_config  # noqa: E402
from docudog.security_labels import format_security_level  # noqa: E402


def _load_state(path: str) -> dict:
    if not os.path.isfile(path):
        return {"files": {}}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if "files" not in data or not isinstance(data["files"], dict):
        data["files"] = {}
    return data


def run_lint(cfg: dict, state: dict, report_path: str) -> list[str]:
    findings: list[str] = []
    files = state.get("files") or {}
    parent = os.path.dirname(os.path.normpath(os.path.expandvars(report_path)))
    audit_path = os.path.join(parent, "DocuDog_audit_log.md")
    raw = str((cfg.get("paths") or {}).get("audit_log_path") or "").strip()
    if raw:
        audit_path = os.path.normpath(os.path.expandvars(raw))
    audit_text = ""
    if os.path.isfile(audit_path):
        try:
            with open(audit_path, encoding="utf-8") as f:
                audit_text = f.read()
        except OSError:
            audit_text = ""

    for path, meta in files.items():
        if not isinstance(meta, dict):
            findings.append(f"[bad_meta] not an object: `{path}`")
            continue
        sec = str(meta.get("security_level") or "").upper()
        name = os.path.basename(path)
        if sec in ("P1", "P2") and name and name not in audit_text:
            findings.append(
                f"[audit_gap] {format_security_level(sec, cfg)} tracked but basename "
                f"not found in audit log: `{name}`"
            )
        summary = str(meta.get("summary") or "").strip()
        if not summary:
            findings.append(f"[empty_summary] `{name}`")
        m = str(meta.get("model_security_level") or "").upper()
        if (
            m
            and sec
            and m != sec
            and not meta.get("owner_override")
            and not meta.get("rule_floor")
        ):
            findings.append(
                f"[level_mismatch] model={m} effective={sec} without owner/rule: `{name}`"
            )
        sha = str(meta.get("sha256") or "")
        if sha and len(sha) != 64:
            findings.append(f"[bad_sha] `{name}` sha256 length={len(sha)}")

    bundles = state.get("context_bundles")
    if isinstance(bundles, list):
        for b in bundles:
            if not isinstance(b, dict):
                continue
            anchor = str(b.get("anchor_path") or "")
            if anchor and anchor not in files:
                findings.append(
                    f"[bundle_orphan] anchor not in state.files: `{os.path.basename(anchor)}`"
                )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="DocuDog governance lint (read-only).")
    parser.add_argument(
        "--config-dir",
        default=ROOT,
        help="Directory with config.json (default: repo root)",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Lint report path (default: next to report_path / DocuDog_lint_report.md)",
    )
    args = parser.parse_args()
    cfg = load_app_config(args.config_dir)
    paths = cfg.get("paths") or {}
    state_path = os.path.normpath(
        os.path.expandvars(
            str(paths.get("state_path") or "%USERPROFILE%/Documents/DocuDog_state.json")
        )
    )
    report_path = os.path.normpath(
        os.path.expandvars(
            str(
                paths.get("report_path")
                or "%USERPROFILE%/Documents/classification_report.md"
            )
        )
    )
    state = _load_state(state_path)
    findings = run_lint(cfg, state, report_path)
    out = args.out.strip()
    if not out:
        out = os.path.join(
            os.path.dirname(report_path), "DocuDog_lint_report.md"
        )
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        "# DocuDog governance lint\n\n",
        f"_Generated {now}. Original documents not modified._\n\n",
        f"- state: `{state_path}`\n",
        f"- findings: **{len(findings)}**\n\n",
    ]
    if findings:
        lines.append("## Findings\n\n")
        for f in findings:
            lines.append(f"- {f}\n")
    else:
        lines.append("_No findings._\n")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(lines)
    print(f"lint_governance: {len(findings)} finding(s) -> {out}")
    return 0 if not findings else 2


if __name__ == "__main__":
    raise SystemExit(main())
