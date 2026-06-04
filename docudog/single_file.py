"""Process one file path without idle wait or the watchdog queue."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from . import lineage, router


def _always_idle() -> float:
    return 1e9


class SingleFileOutcome(str, Enum):
    ANALYZED = "analyzed"
    SKIPPED_UNCHANGED = "skipped_unchanged"
    SKIPPED_FILTER = "skipped_filter"
    SKIPPED_EXTRACT = "skipped_extract"
    SKIPPED_EMPTY = "skipped_empty"
    REQUEUE = "requeue"


@dataclass
class SingleFileResult:
    path: str
    outcome: SingleFileOutcome
    tags: list[str] | None = None
    security_level: str | None = None
    summary: str | None = None
    inference_source: str | None = None
    file_hash: str | None = None


def process_single_path(
    config: dict[str, Any],
    state: dict[str, Any],
    path: str,
    report_path: str,
    state_path: str,
    save_state: Callable[[], None],
    *,
    update_lineage: bool = True,
) -> SingleFileResult:
    """
    Run extract -> classify -> report for one path (idle and queue bypassed).

    Uses the same router.process_file pipeline as the daemon.
    """
    norm = os.path.normpath(os.path.abspath(path))
    if not os.path.isfile(norm):
        raise FileNotFoundError(norm)

    if not router.passes_file_filters(config, norm):
        return SingleFileResult(path=norm, outcome=SingleFileOutcome.SKIPPED_FILTER)

    text, skip_reason = router.extract_document_text(norm)
    if skip_reason:
        router.process_file(
            config,
            state,
            norm,
            report_path,
            state_path,
            idle_trigger_seconds=0.0,
            seconds_since_last_input=_always_idle,
            save_state=save_state,
            file_event_unix=time.time(),
            get_fs_event_snapshot=None,
        )
        return SingleFileResult(path=norm, outcome=SingleFileOutcome.SKIPPED_EXTRACT)
    if not (text and text.strip()):
        return SingleFileResult(path=norm, outcome=SingleFileOutcome.SKIPPED_EMPTY)

    files_state: dict[str, Any] = state.setdefault("files", {})
    before = files_state.get(norm)
    before_analyzed = before.get("last_analyzed_utc") if isinstance(before, dict) else None
    before_hash = before.get("sha256") if isinstance(before, dict) else None

    raw = router.process_file(
        config,
        state,
        norm,
        report_path,
        state_path,
        idle_trigger_seconds=0.0,
        seconds_since_last_input=_always_idle,
        save_state=save_state,
        file_event_unix=time.time(),
        get_fs_event_snapshot=None,
    )

    if raw == "requeue":
        digest = router.sha256_file(norm)
        return SingleFileResult(
            path=norm,
            outcome=SingleFileOutcome.REQUEUE,
            file_hash=digest,
        )

    after = files_state.get(norm)
    after_analyzed = after.get("last_analyzed_utc") if isinstance(after, dict) else None

    if (
        isinstance(after, dict)
        and after_analyzed
        and after_analyzed != before_analyzed
    ):
        if update_lineage:
            try:
                lineage.regenerate_if_enabled(config, state, report_path)
            except Exception:
                import logging

                logging.getLogger(__name__).exception("Lineage update failed after single-file classify")

        return SingleFileResult(
            path=norm,
            outcome=SingleFileOutcome.ANALYZED,
            tags=list(after.get("tags") or []),
            security_level=str(after.get("security_level") or ""),
            summary=str(after.get("summary") or ""),
            inference_source=str(after.get("inference_source") or ""),
            file_hash=str(after.get("sha256") or ""),
        )

    if (
        isinstance(before, dict)
        and isinstance(after, dict)
        and before_hash
        and before_hash == after.get("sha256")
        and before_analyzed == after_analyzed
    ):
        return SingleFileResult(
            path=norm,
            outcome=SingleFileOutcome.SKIPPED_UNCHANGED,
            tags=list(after.get("tags") or []),
            security_level=str(after.get("security_level") or ""),
            summary=str(after.get("summary") or ""),
            inference_source=str(after.get("inference_source") or ""),
            file_hash=str(after.get("sha256") or ""),
        )

    return SingleFileResult(path=norm, outcome=SingleFileOutcome.SKIPPED_EXTRACT)


def format_result_lines(result: SingleFileResult, report_path: str) -> list[str]:
    """Human-readable lines for stdout (no emoji)."""
    lines = [
        f"classify_one: {result.outcome.value}",
        f"  path: {result.path}",
    ]
    if result.file_hash:
        lines.append(f"  sha256: {result.file_hash}")
    if result.tags is not None:
        lines.append(f"  tags: {result.tags}")
    if result.security_level:
        lines.append(f"  security_level: {result.security_level}")
    if result.summary:
        lines.append(f"  summary: {result.summary}")
    if result.inference_source:
        lines.append(f"  inference: {result.inference_source}")
    lines.append(f"  report: {os.path.normpath(os.path.expandvars(report_path))}")
    return lines
