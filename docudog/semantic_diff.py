"""Semantic change log: summary_history + optional one-line LLM/heuristic diff."""

from __future__ import annotations

import logging
import os
import re
from difflib import unified_diff
from typing import Any

logger = logging.getLogger(__name__)


def semantic_enabled(cfg: dict[str, Any]) -> bool:
    raw = cfg.get("semantic_settings")
    if isinstance(raw, dict):
        return bool(raw.get("enabled", True))
    # default on for history; LLM off unless asked
    return True


def llm_diff_enabled(cfg: dict[str, Any]) -> bool:
    raw = cfg.get("semantic_settings")
    if not isinstance(raw, dict):
        return False
    return bool(raw.get("llm_change_summary", False))


def _settings(cfg: dict[str, Any]) -> dict[str, Any]:
    raw = cfg.get("semantic_settings")
    return raw if isinstance(raw, dict) else {}


def make_text_delta(old_text: str, new_text: str, *, max_chars: int = 900) -> str:
    """Compact unified-diff style delta (new vs previous extract)."""
    a = (old_text or "").splitlines()
    b = (new_text or "").splitlines()
    if not a and not b:
        return ""
    # Prefer shorter line-level view
    lines = list(
        unified_diff(a[:200], b[:200], lineterm="", n=1)
    )
    # drop ---/+++ headers noise somewhat
    body = "\n".join(ln for ln in lines if ln and not ln.startswith(("---", "+++", "@@")))
    if not body.strip():
        # fallback: truncated new head
        return (new_text or "")[:max_chars]
    return body[:max_chars]


def heuristic_change_line(prev_summary: str, new_summary: str, delta: str) -> str:
    prev = (prev_summary or "").strip()
    new = (new_summary or "").strip()
    if prev and new and prev != new:
        return f"요약 갱신: {prev[:80]} → {new[:80]}"
    if delta.strip():
        added = len(re.findall(r"^\+[^+]", delta, flags=re.M))
        removed = len(re.findall(r"^-[^-]", delta, flags=re.M))
        return f"본문 변경 감지(+{added}/-{removed} 줄 샘플)"
    return "내용 해시 변경 (세부 델타 없음)"


def llm_change_summary(
    prev_summary: str,
    new_summary: str,
    delta: str,
    cfg: dict[str, Any],
) -> str:
    if not llm_diff_enabled(cfg):
        return ""
    from . import inference

    s = _settings(cfg)
    max_tok = int(s.get("llm_max_tokens", 128))
    system = (
        "Summarize the document change in one short Korean sentence. "
        "Focus on meaning (numbers, dates, sections), not formatting. "
        "No JSON. Plain text only."
    )
    user = (
        f"이전 요약: {prev_summary[:400]}\n"
        f"새 요약: {new_summary[:400]}\n"
        f"델타 샘플:\n{delta[:700]}"
    )
    raw = inference.run_aux_completion(
        system,
        user,
        cfg,
        max_tok,
        task_log_label="semantic_change",
    )
    return " ".join((raw or "").split())[:240]


def build_change_line(
    prev_summary: str,
    new_summary: str,
    old_text: str,
    new_text: str,
    cfg: dict[str, Any],
) -> str:
    s = _settings(cfg)
    max_delta = int(s.get("delta_max_chars", 900))
    delta = make_text_delta(old_text, new_text, max_chars=max_delta)
    line = ""
    try:
        line = llm_change_summary(prev_summary, new_summary, delta, cfg)
    except Exception:
        logger.debug("semantic LLM change summary failed", exc_info=True)
    if not line:
        line = heuristic_change_line(prev_summary, new_summary, delta)
    return line


def lineage_peer_change_line(
    cfg: dict[str, Any],
    state: dict[str, Any],
    new_path: str,
    new_summary: str,
    new_text: str,
) -> str:
    """One-line change vs the previous member of the same lineage/version group."""
    from .lineage import _build_multi_groups

    files = state.get("files") if isinstance(state.get("files"), dict) else {}
    rows: list[tuple[str, dict[str, Any]]] = []
    for path, meta in files.items():
        if isinstance(meta, dict) and meta.get("sha256"):
            rows.append((path, meta))
    if len(rows) < 2:
        return ""
    multi, _s, _n = _build_multi_groups(rows, cfg)
    for _gk, members in multi:
        if new_path not in {p for p, _m in members}:
            continue
        others = [
            (p, m)
            for p, m in members
            if os.path.normcase(p) != os.path.normcase(new_path)
        ]
        if not others:
            continue
        others.sort(
            key=lambda pm: str(pm[1].get("last_analyzed_utc") or ""),
            reverse=True,
        )
        prev_path, prev_meta = others[0]
        old_text = ""
        try:
            from .router import extract_document_text

            t, skip = extract_document_text(prev_path, cfg)
            if not skip and t:
                old_text = t[:2000]
        except Exception:
            logger.debug("peer extract failed for %s", prev_path, exc_info=True)
        return build_change_line(
            str(prev_meta.get("summary") or ""),
            new_summary,
            old_text,
            (new_text or "")[:2000],
            cfg,
        )
    return ""


def push_summary_history(
    meta: dict[str, Any],
    *,
    sha256: str,
    summary: str,
    utc: str,
    change_summary: str = "",
    max_entries: int = 8,
) -> None:
    hist = meta.get("summary_history")
    if not isinstance(hist, list):
        hist = []
    entry: dict[str, Any] = {
        "sha256": sha256,
        "summary": summary,
        "utc": utc,
    }
    if change_summary:
        entry["change_summary"] = change_summary
    hist.append(entry)
    meta["summary_history"] = hist[-max(1, max_entries) :]
    if change_summary:
        meta["last_change_summary"] = change_summary
        meta["last_change_utc"] = utc


def recent_changes_from_state(
    state: dict[str, Any],
    *,
    limit: int = 8,
) -> list[dict[str, Any]]:
    files = state.get("files") if isinstance(state.get("files"), dict) else {}
    rows: list[dict[str, Any]] = []
    for path, meta in files.items():
        if not isinstance(meta, dict):
            continue
        ch = str(meta.get("last_change_summary") or "").strip()
        if not ch:
            continue
        rows.append(
            {
                "path": path,
                "change_summary": ch,
                "utc": str(meta.get("last_change_utc") or meta.get("last_analyzed_utc") or ""),
            }
        )
    rows.sort(key=lambda r: r.get("utc") or "", reverse=True)
    return rows[: max(1, limit)]
