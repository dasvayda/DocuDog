"""Action digest — compressed next-actions from state / audit (no LLM)."""

from __future__ import annotations

import os
import re
from collections import Counter
from typing import Any

from .security_labels import format_security_level

_SHARING_RE = re.compile(r"\[sharing:\s*([a-z_]+)\]", re.I)


def _parse_audit_sharing(audit_path: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    if not os.path.isfile(audit_path):
        return counts
    try:
        with open(audit_path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return counts
    for m in _SHARING_RE.finditer(text):
        counts[m.group(1).lower()] += 1
    return counts


def build_action_lines(
    cfg: dict[str, Any],
    state: dict[str, Any],
    report_path: str,
    *,
    max_lines: int = 6,
) -> list[str]:
    """Return short bullet lines: what to do next."""
    files = state.get("files") if isinstance(state.get("files"), dict) else {}
    ops = state.get("ops") if isinstance(state.get("ops"), dict) else {}
    parent = os.path.dirname(os.path.normpath(os.path.expandvars(report_path)))
    audit_path = os.path.join(parent, "DocuDog_audit_log.md")
    paths = cfg.get("paths") or {}
    raw_audit = str(paths.get("audit_log_path") or "").strip()
    if raw_audit:
        audit_path = os.path.normpath(os.path.expandvars(raw_audit))

    lines: list[str] = []
    p1 = sum(
        1
        for m in files.values()
        if isinstance(m, dict) and str(m.get("security_level") or "").upper() == "P1"
    )
    p2 = sum(
        1
        for m in files.values()
        if isinstance(m, dict) and str(m.get("security_level") or "").upper() == "P2"
    )
    if p1 or p2:
        lines.append(
            f"민감 등급 추적: {format_security_level('P1', cfg)} {p1}건 · "
            f"{format_security_level('P2', cfg)} {p2}건 — audit/리포트에서 공유 전 확인"
        )

    sharing = _parse_audit_sharing(audit_path)
    if sharing.get("redact_before_external"):
        lines.append(
            f"외부 공유 전 확인 필요(redact): **{sharing['redact_before_external']}**건 "
            f"(audit Handling hint)"
        )
    if sharing.get("internal_only"):
        lines.append(
            f"내부 전용 권고(internal_only): **{sharing['internal_only']}**건"
        )

    mismatch = 0
    for meta in files.values():
        if not isinstance(meta, dict):
            continue
        if meta.get("owner_override"):
            continue
        m = str(meta.get("model_security_level") or "").upper()
        e = str(meta.get("security_level") or "").upper()
        # after rules, model_* is pre-merge; if rule floor changed effective vs model
        rule = meta.get("rule_floor")
        if rule and str(rule).upper() != m and e == str(rule).upper():
            mismatch += 1
        elif m and e and m != e:
            mismatch += 1
    if mismatch:
        lines.append(f"등급 상향/불일치 의심 재검토: **{mismatch}**건 (규칙 바닥·오버라이드)")

    sens = int(ops.get("skip_extract_sensitive_count") or 0)
    skip_n = int(ops.get("skip_extract_count") or 0)
    if sens:
        lines.append(
            f"미분류·민감 파일명: **{sens}**건 — 수동 열람 또는 추출 지원 확장 검토"
        )
    elif skip_n:
        lines.append(f"미분류(추출 스킵) 누적: **{skip_n}**건")

    related_hits = 0
    for meta in files.values():
        if isinstance(meta, dict) and meta.get("related_paths"):
            related_hits += 1
    if related_hits:
        lines.append(f"최근 유사·맥락 후보가 있는 파일: **{related_hits}**건 (status 하단)")

    from . import cadence

    for r in cadence.evaluate_cadence(cfg, state):
        if r.get("status") == "miss":
            lines.append(f"주기 미검출: {r.get('message')}")

    if not lines:
        lines.append("당장 표시할 액션 없음 — 신규 분류·스킵이 쌓이면 여기가 갱신됨")
    return lines[: max(1, max_lines)]


def format_action_digest_md(
    cfg: dict[str, Any],
    state: dict[str, Any],
    report_path: str,
) -> str:
    bullets = build_action_lines(cfg, state, report_path)
    out = ["## 지금 할 일 (다이제스트)\n\n"]
    for b in bullets:
        out.append(f"- {b}\n")
    out.append("\n")
    return "".join(out)
