"""Routing: filters, hashing, text extraction, dedupe, inference + reporting."""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import audit
from . import context_bundles
from . import inference
from . import owner_tags
from . import reporter

logger = logging.getLogger(__name__)

_SKIPPABLE_FOR_MVP = {".pdf", ".hwp", ".hwpx"}


def _normalize_path(path: str) -> str:
    return os.path.normpath(os.path.abspath(path))


def passes_file_filters(config: dict[str, Any], path: str) -> bool:
    filters = config.get("file_filters", {})
    exts = {e.lower() for e in filters.get("allowed_extensions", [])}
    ext = Path(path).suffix.lower()
    if ext not in exts:
        return False
    size = filters.get("size_limit", {})
    min_b = int(size.get("min_bytes", 0))
    max_b = int(size.get("max_bytes", 2**62))
    try:
        sz = os.path.getsize(path)
    except OSError:
        return False
    return min_b <= sz <= max_b


def sha256_file(path: str, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _read_plain_text(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _read_docx(path: str) -> str:
    import docx  # type: ignore[import-untyped]

    document = docx.Document(path)
    parts: list[str] = []
    for p in document.paragraphs:
        t = (p.text or "").strip()
        if t:
            parts.append(t)
    for table in document.tables:
        for row in table.rows:
            cells = " | ".join((c.text or "").strip() for c in row.cells)
            if cells.strip():
                parts.append(cells)
    return "\n".join(parts)


def _read_pptx(path: str) -> str:
    from pptx import Presentation  # type: ignore[import-untyped]

    prs = Presentation(path)
    out: list[str] = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if not hasattr(shape, "text"):
                continue
            t = (shape.text or "").strip()
            if t:
                out.append(t)
    return "\n".join(out)


def _read_xlsx(path: str) -> str:
    from openpyxl import load_workbook  # type: ignore[import-untyped]

    wb = load_workbook(filename=path, read_only=True, data_only=True)
    lines: list[str] = []
    try:
        for sheet in wb.worksheets:
            for row in sheet.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None and str(c).strip()]
                if cells:
                    lines.append(" | ".join(cells))
    finally:
        wb.close()
    return "\n".join(lines)


def extract_document_text(path: str) -> tuple[str | None, str | None]:
    """
    Return (text, skip_reason). skip_reason is set when routing should stop
    without treating as an error (e.g., MVP skips PDF/HWP).
    """
    ext = Path(path).suffix.lower()
    if ext in _SKIPPABLE_FOR_MVP:
        return None, f"MVP 스킵: 이 확장자는 텍스트 추출 미구현 ({ext})"

    try:
        if ext in {".txt", ".md"}:
            return _read_plain_text(path), None
        if ext == ".docx":
            return _read_docx(path), None
        if ext == ".pptx":
            return _read_pptx(path), None
        if ext == ".xlsx":
            return _read_xlsx(path), None
    except Exception as e:
        logger.debug("텍스트 추출 실패: %s — %s", path, e)
        logger.debug("Extract traceback", exc_info=True)
        return None, f"텍스트 추출 실패: {e}"

    return None, f"지원되지 않는 확장자: {ext}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def process_file(
    config: dict[str, Any],
    state: dict[str, Any],
    path: str,
    report_path: str,
    state_path: str,
    idle_trigger_seconds: float,
    seconds_since_last_input: Callable[[], float],
    save_state: Callable[[], None],
    file_event_unix: float | None = None,
    get_fs_event_snapshot: Callable[[], list[tuple[str, float]]] | None = None,
) -> str | None:
    """
    Full routing for one file: filters, extract, hash, dedupe, inference, report.

    state_path: used to locate DocuDog_tag_overrides.json next to state.

    Returns:
        None — finished handling (including filters/skips and successful analysis).
        "requeue" — same path should be enqueued again (user active / yielded).

    Yield / pause: if the user becomes active during streaming inference, we stop
    without writing partial results; caller should requeue the path.
    """
    norm = _normalize_path(path)
    files_state: dict[str, Any] = state.setdefault("files", {})

    if not passes_file_filters(config, norm):
        logger.debug("Skip (filter): %s", norm)
        return None

    text, skip_reason = extract_document_text(norm)
    if skip_reason:
        logger.debug("Skip: %s — %s", norm, skip_reason)
        reporter.append_note(report_path, f"{skip_reason} — `{norm}`")
        return None
    if not (text and text.strip()):
        logger.debug("Skip (empty text): %s", norm)
        return None

    digest = sha256_file(norm)
    prev = files_state.get(norm)

    if isinstance(prev, dict) and prev.get("sha256") == digest:
        prev["last_checked_utc"] = _utc_now_iso()
        files_state[norm] = prev
        save_state()
        logger.debug("Skip LLM (unchanged content hash): %s", norm)
        return None

    def user_active() -> bool:
        return seconds_since_last_input() < float(idle_trigger_seconds)

    if user_active():
        logger.info("Defer (user active before inference): %s", norm)
        return "requeue"

    try:
        result = inference.classify_document(
            text,
            config,
            should_yield=user_active,
        )
    except inference.YieldToUser:
        logger.info("Yielded during inference (user active): %s", norm)
        return "requeue"

    inf_src = str(result.pop(inference.DOCUDOG_META_SOURCE, "mock"))
    inf_reason = str(result.pop(inference.DOCUDOG_META_REASON, ""))

    tags = result.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    sec = str(result.get("security_level", ""))
    summary = str(result.get("summary", ""))

    model_tags = list(tags)
    model_sec = sec
    overrides_doc = owner_tags.load_tag_overrides(config, state_path)
    tags, sec, owner_applied = owner_tags.merge_owner_tags(
        norm, model_tags, model_sec, overrides_doc
    )

    analyzed_at = datetime.now(timezone.utc)
    reporter.append_classification(
        report_path=report_path,
        analyzed_at_utc=analyzed_at,
        file_name=os.path.basename(norm),
        file_hash=digest,
        tags=tags,
        security_level=sec,
        summary=summary,
        inference_source=inf_src,
        inference_reason=inf_reason,
        owner_tags_applied=owner_applied,
    )

    excerpt_lim = 1200
    acfg = config.get("audit_settings")
    if isinstance(acfg, dict) and acfg.get("max_excerpt_chars") is not None:
        try:
            excerpt_lim = int(acfg["max_excerpt_chars"])
        except (TypeError, ValueError):
            excerpt_lim = 1200
    audit.maybe_record_sensitive_classification(
        config,
        norm_path=norm,
        report_path=report_path,
        analyzed_at_utc=analyzed_at,
        file_hash=digest,
        tags=tags,
        security_level=sec,
        text_excerpt=text[: max(0, excerpt_lim)],
        inference_source=inf_src,
    )

    files_state[norm] = {
        "sha256": digest,
        "last_analyzed_utc": analyzed_at.isoformat(),
        "last_checked_utc": _utc_now_iso(),
        "summary": summary,
        "model_tags": model_tags,
        "model_security_level": model_sec,
        "tags": tags,
        "security_level": sec,
        "owner_override": owner_applied,
        "inference_source": inf_src,
        "inference_reason": inf_reason,
    }
    state["last_inference_backend"] = inf_src
    state["last_inference_utc"] = analyzed_at.isoformat()
    save_state()
    logger.info(
        "Analyzed: %s [inference=%s]",
        os.path.basename(norm),
        inf_src,
    )
    if get_fs_event_snapshot is not None and file_event_unix is not None:
        try:
            snap = get_fs_event_snapshot()
            context_bundles.update_bundles_after_analysis(
                config, state, norm, float(file_event_unix), snap, save_state
            )
        except Exception:
            logger.exception("Context bundle update failed for %s", norm)
    return None
