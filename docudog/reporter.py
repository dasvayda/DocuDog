"""Append-only markdown audit timeline for classifications."""

from __future__ import annotations

import logging
import os
import re
import threading
from datetime import datetime, timezone
from typing import Iterable

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()

_REAL_BACKEND_SOURCES = frozenset({"lite_rt", "lm_studio", "openai_compatible"})

_FOOTER_PATTERN = re.compile(
    r"\r?\n<!-- docudog-meta:start -->.*?\r?\n<!-- docudog-meta:end -->\r?\n?",
    re.DOTALL,
)


def _split_report_core_and_trailing(body: str) -> tuple[str, str]:
    """
    Remove at most one docudog footer block; return (core, text_that_was_after_footer).
    Preserves append_note lines that were written after the footer.
    """
    m = _FOOTER_PATTERN.search(body)
    if not m:
        return body.rstrip() + "\n", ""
    core = body[: m.start()].rstrip() + "\n"
    trailing = body[m.end() :].lstrip("\r\n")
    return core, trailing


def _expand(path: str) -> str:
    return os.path.normpath(os.path.expandvars(path))


def _sanitize_cell(value: str) -> str:
    """Keep table rows on one line; avoid breaking pipe tables."""
    return " ".join(value.replace("|", "\\|").split())


def _report_has_inference_column(report_path: str) -> bool:
    """기존 리포트(6열)와 호환: Inference 열이 없으면 새 열 없이 append."""
    if not os.path.isfile(report_path):
        return True
    try:
        with open(report_path, encoding="utf-8") as f:
            head = f.read(8000)
    except OSError:
        return True
    return "| Inference |" in head


def _format_report_timestamp(dt: datetime) -> str:
    """
    표시용 시각: 저장은 UTC로 해도 리포트에는 OS 로컬(한국 PC면 KST)으로 변환.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone()
    wall = local.strftime("%Y-%m-%d %H:%M:%S")
    tz_name = local.tzname()
    if tz_name and tz_name != "UTC":
        return f"{wall} {tz_name}"
    # 일부 환경에서 tzname 비어 있음 → 숫자 오프셋
    off = local.strftime("%z")
    if off:
        return f"{wall} (UTC{off[:3]}:{off[3:]})"
    return wall


def _last_inference_footer_md(inference_source: str, analyzed_at_utc: datetime) -> str:
    """Single-line markdown footer; replaced on each successful classification append."""
    ts = _format_report_timestamp(analyzed_at_utc)
    src = _sanitize_cell(str(inference_source).strip() or "unknown")
    return (
        "\n<!-- docudog-meta:start -->\n\n"
        f"_Last inference: `{src}` · {ts}_\n\n"
        "<!-- docudog-meta:end -->\n"
    )



def append_classification(
    report_path: str,
    analyzed_at_utc: datetime,
    file_name: str,
    file_hash: str,
    tags: Iterable[str],
    security_level: str,
    summary: str,
    inference_source: str = "mock",
    inference_reason: str = "",
    owner_tags_applied: bool = False,
) -> None:
    """Append one markdown table row to the report (creates file + header if needed)."""
    path = _expand(report_path)

    tags_joined = ", ".join(tags)
    time_str = _format_report_timestamp(analyzed_at_utc)
    summary_one_line = _sanitize_cell(summary.replace("\r\n", "\n").replace("\n", " / "))
    infer_real = inference_source in _REAL_BACKEND_SOURCES

    use_infer_col = _report_has_inference_column(path)
    if infer_real and owner_tags_applied:
        if inference_reason:
            infer_cell = f"{inference_source} + owner ({_sanitize_cell(inference_reason)})"
        else:
            infer_cell = f"{inference_source} + owner tags"
    elif infer_real and inference_reason:
        infer_cell = f"{inference_source} ({_sanitize_cell(inference_reason)})"
    elif infer_real:
        infer_cell = inference_source
    elif inference_reason:
        infer_cell = f"mock ({_sanitize_cell(inference_reason)[:56]})"
    else:
        infer_cell = "mock"

    if use_infer_col:
        row = (
            f"| {time_str} | {_sanitize_cell(file_name)} | `{file_hash}` | "
            f"{_sanitize_cell(tags_joined)} | {_sanitize_cell(security_level)} | {_sanitize_cell(infer_cell)} | "
            f"{summary_one_line} |\n"
        )
        header = (
            "# DocuDog classification report\n\n"
            "로컬 누적 감사 로그. **Inference** 열: `lite_rt` = LiteRT-LM, "
            "`lm_studio` / `openai_compatible` = 로컬/원격 chat API, "
            "`mock` = 모의 결과. `+ owner` = `DocuDog_tag_overrides.json` 적용.\n\n"
            "| Analyzed At (local) | File | SHA-256 | Tags | Security | Inference | Summary |\n"
            "|---|---|---|---|---|---|---|\n"
        )
    else:
        row = (
            f"| {time_str} | {_sanitize_cell(file_name)} | `{file_hash}` | "
            f"{_sanitize_cell(tags_joined)} | {_sanitize_cell(security_level)} | {summary_one_line} |\n"
        )
        header = (
            "# DocuDog classification report\n\n"
            "로컬 누적 감사 로그 (네트워크 전송 없음).\n\n"
            "| Analyzed At (local) | File | SHA-256 | Tags | Security | Summary |\n"
            "|---|---|---|---|---|---|\n"
        )

    footer = _last_inference_footer_md(inference_source, analyzed_at_utc)
    with _write_lock:
        path = _expand(report_path)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        is_new = not os.path.isfile(path)
        if is_new:
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(header)
                f.write(row)
                f.write(footer)
        else:
            try:
                with open(path, encoding="utf-8") as f:
                    body = f.read()
            except OSError as e:
                logger.warning("Report read failed for footer update (%s): %s", path, e)
                with open(path, "a", encoding="utf-8", newline="\n") as f:
                    f.write(row)
                    f.write(footer)
            else:
                core, trailing = _split_report_core_and_trailing(body)
                new_body = core + row + footer
                if trailing:
                    new_body = new_body.rstrip() + "\n\n" + trailing
                if not new_body.endswith("\n"):
                    new_body += "\n"
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(new_body)
    logger.debug("Appended report row for %s", file_name)


def append_note(report_path: str, message: str) -> None:
    """Append a plain note line (e.g., skipped formats) for traceability."""
    path = _expand(report_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    ts = _format_report_timestamp(datetime.now(timezone.utc))
    line = f"\n> [{ts}] {message}\n"
    with _write_lock:
        with open(path, "a", encoding="utf-8", newline="\n") as f:
            f.write(line)
