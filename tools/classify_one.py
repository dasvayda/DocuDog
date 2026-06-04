#!/usr/bin/env python3
"""Classify a single file: extract -> LLM -> stdout + classification_report row.

No idle wait, no watchdog queue. Uses config.json from the repo root (or --config-dir).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from docudog import inference, single_file  # noqa: E402
from main import load_config, load_state, save_state_atomic  # noqa: E402


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        stream=sys.stdout,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Classify one document through DocuDog (no idle / no watcher)."
    )
    parser.add_argument("path", help="Absolute or relative path to one file")
    parser.add_argument(
        "--config-dir",
        default=ROOT,
        help="Directory containing config.json (default: repo root)",
    )
    parser.add_argument(
        "--state",
        default="",
        help="Override paths.state_path from config (expanded env vars allowed)",
    )
    parser.add_argument(
        "--report",
        default="",
        help="Override paths.report_path from config",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="DEBUG logs")
    args = parser.parse_args()

    from docudog.env_litert import apply_litert_env_defaults

    apply_litert_env_defaults()
    _setup_logging(args.verbose)

    config_dir = os.path.normpath(os.path.abspath(args.config_dir))
    cfg_path = os.path.join(config_dir, "config.json")
    if not os.path.isfile(cfg_path):
        print(f"classify_one: config.json not found at {cfg_path}", file=sys.stderr)
        return 2

    cfg = load_config(cfg_path)
    inference.log_inference_runtime_summary(cfg)

    paths = cfg.get("paths", {})
    state_path = args.state or paths.get(
        "state_path",
        os.path.join("%USERPROFILE%", "Documents", "DocuDog_state.json"),
    )
    report_path = args.report or paths.get(
        "report_path",
        os.path.join("%USERPROFILE%", "Documents", "classification_report.md"),
    )
    state_path = os.path.normpath(os.path.expandvars(str(state_path)))
    report_path = os.path.normpath(os.path.expandvars(str(report_path)))

    target = os.path.normpath(os.path.abspath(args.path))
    if not os.path.isfile(target):
        print(f"classify_one: file not found: {target}", file=sys.stderr)
        return 2

    state = load_state(state_path)

    def persist() -> None:
        save_state_atomic(state_path, state)

    try:
        result = single_file.process_single_path(
            cfg,
            state,
            target,
            report_path,
            state_path,
            persist,
        )
    except FileNotFoundError as e:
        print(f"classify_one: {e}", file=sys.stderr)
        return 2
    except Exception:
        logging.getLogger(__name__).exception("classify_one failed for %s", target)
        return 1

    for line in single_file.format_result_lines(result, report_path):
        print(line)

    if result.outcome == single_file.SingleFileOutcome.REQUEUE:
        return 1
    if result.outcome in (
        single_file.SingleFileOutcome.SKIPPED_FILTER,
        single_file.SingleFileOutcome.SKIPPED_EXTRACT,
        single_file.SingleFileOutcome.SKIPPED_EMPTY,
    ):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
