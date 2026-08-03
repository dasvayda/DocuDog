"""High-sensitivity (P1/P2) local audit log + optional LLM handling hint."""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any

from . import inference
from .reporter import _format_report_timestamp, _sanitize_cell
from .security_labels import format_security_level

logger = logging.getLogger(__name__)
_write_lock = threading.Lock()


def _expand_audit_path(cfg: dict[str, Any], report_path: str) -> str:
    paths = cfg.get("paths") or {}
    raw = str(paths.get("audit_log_path") or "").strip()
    if raw:
        return os.path.normpath(os.path.expandvars(raw))
    return os.path.join(
        os.path.dirname(os.path.normpath(os.path.expandvars(report_path))),
        "DocuDog_audit_log.md",
    )


def append_audit_row(
    audit_path: str,
    *,
    analyzed_at_utc: datetime,
    file_name: str,
    file_hash: str,
    security_level: str,
    tags: list[str],
    handling_note: str,
    inference_source: str,
    config: dict[str, Any] | None = None,
) -> None:
    path = os.path.normpath(os.path.expandvars(audit_path))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    time_str = _format_report_timestamp(analyzed_at_utc)
    tags_joined = ", ".join(tags)
    note_cell = handling_note.replace("\r\n", "\n").replace("\n", " / ")
    level_cell = format_security_level(security_level, config)
    row = (
        f"| {time_str} | {_sanitize_cell(file_name)} | `{file_hash}` | "
        f"{_sanitize_cell(level_cell)} | {_sanitize_cell(tags_joined)} | "
        f"{_sanitize_cell(inference_source)} | {_sanitize_cell(note_cell)} |\n"
    )
    header = (
        "# DocuDog audit log (P1/P2)\n\n"
        "로컬 감사 전용. **P1**·**P2** 분류 시 한 행이 추가됩니다. "
        "네트워크 전송 없음. 액션 요약은 `DocuDog_status.md`의 "
        "「지금 할 일」을 본다.\n\n"
        "| At (local) | File | SHA-256 | Level | Tags | Inference | Handling hint |\n"
        "|---|---|---|---|---|---|---|\n"
    )
    with _write_lock:
        is_new = not os.path.isfile(path)
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            if is_new:
                f.write(header)
            f.write(row)
    logger.info("Audit log appended for %s (%s)", file_name, security_level)


def maybe_record_sensitive_classification(
    cfg: dict[str, Any],
    *,
    norm_path: str,
    report_path: str,
    analyzed_at_utc: datetime,
    file_hash: str,
    tags: list[str],
    security_level: str,
    text_excerpt: str,
    inference_source: str,
) -> None:
    audit_cfg = cfg.get("audit_settings")
    if not isinstance(audit_cfg, dict):
        audit_cfg = {}
    if not bool(audit_cfg.get("enabled", True)):
        return
    if security_level not in ("P1", "P2"):
        return

    handling = ""
    if bool(audit_cfg.get("llm_handling_hint", True)):
        hint = inference.audit_handling_suggestion(text_excerpt, security_level, cfg)
        if hint:
            handling = f"{hint['handling_note']} [sharing: {hint['sharing']}]"

    append_audit_row(
        _expand_audit_path(cfg, report_path),
        analyzed_at_utc=analyzed_at_utc,
        file_name=os.path.basename(norm_path),
        file_hash=file_hash,
        security_level=security_level,
        tags=tags,
        handling_note=handling,
        inference_source=inference_source,
        config=cfg,
    )
    try:
        from . import activity

        activity.append_activity(
            cfg,
            report_path,
            "audit",
            f"{norm_path} | {security_level}",
            when=analyzed_at_utc,
        )
    except Exception:
        logger.exception("Activity log [audit] failed")
