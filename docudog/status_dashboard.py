"""DocuDog_status.md — short operational dashboard (not lineage archive)."""

from __future__ import annotations

import logging
import os
from collections import Counter
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from . import reporter, skip_insights
from .security_labels import format_security_level

logger = logging.getLogger(__name__)


def resolve_status_path(cfg: dict[str, Any], report_path: str) -> str:
    paths = cfg.get("paths") or {}
    raw = str(paths.get("status_path") or "").strip()
    if raw:
        return os.path.normpath(os.path.expandvars(raw))
    return os.path.join(
        os.path.dirname(os.path.normpath(os.path.expandvars(report_path))),
        "DocuDog_status.md",
    )


def status_enabled(cfg: dict[str, Any]) -> bool:
    raw = cfg.get("status_settings")
    if isinstance(raw, dict) and "enabled" in raw:
        return bool(raw.get("enabled"))
    return True


def _parse_day(iso: str) -> str:
    s = (iso or "").strip()
    if not s:
        return ""
    return s[:10]


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _newest_in_group(members: list[tuple[str, dict[str, Any]]]) -> tuple[str, dict[str, Any]]:
    def key(item: tuple[str, dict[str, Any]]) -> str:
        meta = item[1]
        return str(meta.get("last_analyzed_utc") or meta.get("last_checked_utc") or "")

    return max(members, key=key)


def build_status_markdown(
    cfg: dict[str, Any],
    state: dict[str, Any],
    report_path: str,
) -> str:
    files = state.get("files") if isinstance(state.get("files"), dict) else {}
    today = _today_utc()
    level_counts: Counter[str] = Counter()
    today_n = 0
    backend_by_level: dict[str, Counter[str]] = {}
    for _path, meta in files.items():
        if not isinstance(meta, dict):
            continue
        sec = str(meta.get("security_level") or "").upper()
        if sec:
            level_counts[sec] += 1
            bk = str(meta.get("inference_source") or "unknown")
            backend_by_level.setdefault(sec, Counter())[bk] += 1
        day = _parse_day(str(meta.get("last_analyzed_utc") or ""))
        if day == today:
            today_n += 1

    ops = state.get("ops") if isinstance(state.get("ops"), dict) else {}
    skip_n = int(ops.get("skip_extract_count") or 0)
    sens_n = int(ops.get("skip_extract_sensitive_count") or 0)
    banner = skip_insights.format_blind_spot_banner(state)

    p1 = level_counts.get("P1", 0)
    p2 = level_counts.get("P2", 0)
    last_backend = str(state.get("last_inference_backend") or "(none)")
    last_utc = str(state.get("last_inference_utc") or "")

    lines: list[str] = [
        "# DocuDog status\n",
        "\n",
        "_현황 대시보드 (짧게·자주 갱신). 상세 lineage/전체 표는 아래 링크._\n",
        "\n",
    ]
    if banner:
        lines.append(f"> **경고:** {banner}\n\n")

    from . import action_digest
    from . import cadence

    lines.append(action_digest.format_action_digest_md(cfg, state, report_path))

    cad_results = cadence.evaluate_cadence(cfg, state)
    cad_md = cadence.format_cadence_status_md(cad_results)
    if cad_md:
        lines.append(cad_md)

    lines.append("## 오늘 / 최근\n\n")
    lines.append(
        f"- 오늘 분류(UTC 날짜 기준): **{today_n}**건\n"
        f"- 추적 파일(state): **{len(files)}** · "
        f"P1 **{p1}** · P2 **{p2}** · "
        f"미분류 누적 스킵 **{skip_n}**"
        + (f" (개인정보 키워드 {sens_n})" if sens_n else "")
        + "\n"
        f"- 마지막 추론: `{last_backend}`"
        + (f" · `{last_utc}`" if last_utc else "")
        + "\n\n"
    )

    if level_counts:
        lines.append("## 등급 분포 (라벨)\n\n")
        for code in ("P1", "P2", "P3", "P4"):
            if code not in level_counts:
                continue
            label = format_security_level(code, cfg)
            lines.append(f"- {label}: **{level_counts[code]}**\n")
            bk = backend_by_level.get(code)
            if bk:
                parts = ", ".join(f"{k}={v}" for k, v in bk.most_common(4))
                lines.append(f"  - backend 분포: {parts}\n")
        lines.append("\n")
        lines.append(
            "> 참고: 보안 등급은 규칙 엔진 없이 모델 출력에 의존할 수 있음. "
            "backend가 바뀌면 등급 분포가 흔들릴 수 있음.\n\n"
        )

    # Top multi-version hints from filename lineage keys
    from .lineage import lineage_group_key

    groups: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for path, meta in files.items():
        if not isinstance(meta, dict):
            continue
        key = lineage_group_key(os.path.basename(path))
        if not key:
            continue
        groups.setdefault(key, []).append((path, meta))
    multi = [(k, m) for k, m in groups.items() if len(m) >= 2]
    multi.sort(key=lambda km: len(km[1]), reverse=True)
    if multi:
        lines.append("## 권장 최신본 (다중 버전 그룹 Top)\n\n")
        for key, members in multi[:8]:
            newest_path, newest_meta = _newest_in_group(members)
            sec = format_security_level(str(newest_meta.get("security_level") or ""), cfg)
            lines.append(
                f"- `{key}` ({len(members)} files) → "
                f"`{os.path.basename(newest_path)}`"
                + (f" · {sec}" if sec else "")
                + "\n"
            )
        lines.append("\n")

    last_rel = state.get("last_related")
    if isinstance(last_rel, dict) and last_rel.get("paths"):
        lines.append("## 이 파일과 같이 볼 후보 (최근 분류)\n\n")
        anchor = str(last_rel.get("anchor") or "")
        if anchor:
            lines.append(f"- 앵커: `{os.path.basename(anchor)}`\n")
        for p in list(last_rel.get("paths") or [])[:6]:
            lines.append(f"- `{os.path.basename(str(p))}`\n")
        lines.append("\n")

    from . import semantic_diff

    changes = semantic_diff.recent_changes_from_state(state, limit=6)
    if changes:
        lines.append("## 최근 시맨틱 변경\n\n")
        for ch in changes:
            lines.append(
                f"- `{os.path.basename(str(ch.get('path') or ''))}`: "
                f"{ch.get('change_summary')}\n"
            )
        lines.append("\n")

    # category distribution
    cat_counts: Counter[str] = Counter()
    for meta in files.values():
        if not isinstance(meta, dict):
            continue
        for cid in meta.get("category_ids") or []:
            cat_counts[str(cid)] += 1
    if cat_counts:
        lines.append("## 업무 카테고리\n\n")
        for cid, n in cat_counts.most_common(12):
            lines.append(f"- `{cid}`: **{n}**\n")
        lines.append("\n")

    sens_recent = ops.get("skip_extract_sensitive_recent")
    if isinstance(sens_recent, list) and sens_recent:
        lines.append("## 최근 미분류·민감 파일명\n\n")
        for item in sens_recent[-8:]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"- `{os.path.basename(str(item.get('path') or ''))}` "
                f"(키워드: {item.get('keyword')})\n"
            )
        lines.append("\n")

    rp = os.path.normpath(os.path.expandvars(report_path))
    parent = os.path.dirname(rp)
    lines.append("## 상세 링크\n\n")
    lines.append(f"- 분류 리포트: `{rp}`\n")
    lines.append(f"- HTML: `{reporter.html_path_for_report(rp)}`\n")
    lines.append(f"- Lineage(보관): `{os.path.join(parent, 'DocuDog_lineage.md')}`\n")
    lines.append(f"- Audit: `{os.path.join(parent, 'DocuDog_audit_log.md')}`\n")
    lines.append(f"- Activity: `{os.path.join(parent, 'DocuDog_activity_log.md')}`\n")
    lines.append("\n")
    return "".join(lines)


def write_status(
    cfg: dict[str, Any],
    state: dict[str, Any],
    report_path: str,
    save_state: Callable[[], None] | None = None,
) -> str | None:
    if not status_enabled(cfg):
        return None
    path = resolve_status_path(cfg, report_path)
    body = build_status_markdown(cfg, state, report_path)
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(body)
        reporter.sync_report_html(path)
    except OSError as e:
        logger.warning("Status dashboard write failed (%s): %s", path, e)
        return None
    logger.debug("Wrote status dashboard: %s", path)

    # Cadence miss → activity once per UTC day
    try:
        from . import cadence

        results = cadence.evaluate_cadence(cfg, state)
        ops = state.setdefault("ops", {})
        if not isinstance(ops, dict):
            ops = {}
            state["ops"] = ops
        today = _today_utc()
        if ops.get("last_cadence_log_day") != today:
            cadence.log_cadence_misses(cfg, report_path, results)
            ops["last_cadence_log_day"] = today
            if save_state is not None:
                save_state()
    except Exception:
        logger.exception("Cadence evaluation failed")

    try:
        from . import mobile_digest

        mobile_digest.write_mobile_digest(cfg, state, report_path)
    except Exception:
        logger.exception("Mobile digest write failed")

    return path
