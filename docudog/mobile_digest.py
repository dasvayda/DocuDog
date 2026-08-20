"""Mobile one-screen digest (HTML + JSON) — viewport shrink of status."""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from . import action_digest, cadence, skip_insights
from .security_labels import format_security_level

logger = logging.getLogger(__name__)


def resolve_mobile_digest_path(cfg: dict[str, Any], report_path: str) -> str:
    paths = cfg.get("paths") or {}
    raw = str(paths.get("mobile_digest_path") or "").strip()
    if raw:
        return os.path.normpath(os.path.expandvars(raw))
    return os.path.join(
        os.path.dirname(os.path.normpath(os.path.expandvars(report_path))),
        "DocuDog_mobile_digest.html",
    )


def mobile_digest_enabled(cfg: dict[str, Any]) -> bool:
    raw = cfg.get("mobile_digest_settings")
    if isinstance(raw, dict) and "enabled" in raw:
        return bool(raw.get("enabled"))
    return True


def build_mobile_payload(
    cfg: dict[str, Any],
    state: dict[str, Any],
    report_path: str,
) -> dict[str, Any]:
    files = state.get("files") if isinstance(state.get("files"), dict) else {}
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    today_n = 0
    levels: Counter[str] = Counter()
    for meta in files.values():
        if not isinstance(meta, dict):
            continue
        sec = str(meta.get("security_level") or "").upper()
        if sec:
            levels[sec] += 1
        day = str(meta.get("last_analyzed_utc") or "")[:10]
        if day == today:
            today_n += 1
    ops = state.get("ops") if isinstance(state.get("ops"), dict) else {}
    banner = skip_insights.format_blind_spot_banner(state)
    actions = action_digest.build_action_lines(cfg, state, report_path, max_lines=4)
    cad = cadence.evaluate_cadence(cfg, state)
    misses = [r for r in cad if r.get("status") == "miss"]
    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "today_classified": today_n,
        "p1": levels.get("P1", 0),
        "p2": levels.get("P2", 0),
        "tracked_files": len(files),
        "skip_extract": int(ops.get("skip_extract_count") or 0),
        "skip_sensitive": int(ops.get("skip_extract_sensitive_count") or 0),
        "blind_spot": banner,
        "last_inference_backend": state.get("last_inference_backend") or "",
        "last_inference_utc": state.get("last_inference_utc") or "",
        "actions": actions,
        "cadence_misses": [r.get("message") for r in misses],
        "p1_label": format_security_level("P1", cfg),
        "p2_label": format_security_level("P2", cfg),
        "threads_top": [
            {
                "title": t.get("title"),
                "count": t.get("member_count"),
                "today_n": t.get("today_n"),
            }
            for t in (state.get("threads") or [])[:3]
            if isinstance(t, dict)
        ],
    }


def render_mobile_html(payload: dict[str, Any]) -> str:
    actions = "".join(f"<li>{_esc(a)}</li>" for a in (payload.get("actions") or []))
    misses = "".join(
        f"<li>{_esc(m)}</li>" for m in (payload.get("cadence_misses") or [])
    )
    warn = payload.get("blind_spot") or ""
    warn_html = f'<p class="warn">{_esc(warn)}</p>' if warn else ""
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DocuDog mobile digest</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;padding:1rem;background:#0f172a;color:#e2e8f0}}
h1{{font-size:1.15rem;margin:0 0 .75rem}}
.card{{background:#1e293b;border-radius:12px;padding:.9rem 1rem;margin-bottom:.75rem}}
.big{{font-size:1.6rem;font-weight:700}}
.muted{{color:#94a3b8;font-size:.85rem}}
.warn{{background:#7c2d12;color:#ffedd5;padding:.6rem .75rem;border-radius:8px}}
ul{{margin:.4rem 0 0;padding-left:1.1rem}}
</style>
</head>
<body>
<h1>DocuDog</h1>
{warn_html}
<div class="card">
  <div class="muted">오늘 분류</div>
  <div class="big">{payload.get("today_classified", 0)}</div>
  <div class="muted">{_esc(payload.get("p1_label") or "P1")} {payload.get("p1", 0)}
   · {_esc(payload.get("p2_label") or "P2")} {payload.get("p2", 0)}
   · 미분류 {payload.get("skip_extract", 0)}</div>
</div>
<div class="card">
  <div class="muted">지금 할 일</div>
  <ul>{actions or "<li>(없음)</li>"}</ul>
</div>
{f'<div class="card"><div class="muted">주기 미검출</div><ul>{misses}</ul></div>' if misses else ""}
<div class="card muted">마지막 추론: {_esc(payload.get("last_inference_backend") or "-")}
 · {_esc(str(payload.get("last_inference_utc") or "")[:19])}</div>
</body>
</html>
"""


def _esc(s: object) -> str:
    import html as _html

    return _html.escape(str(s), quote=True)


def write_mobile_digest(
    cfg: dict[str, Any],
    state: dict[str, Any],
    report_path: str,
) -> str | None:
    if not mobile_digest_enabled(cfg):
        return None
    path = resolve_mobile_digest_path(cfg, report_path)
    payload = build_mobile_payload(cfg, state, report_path)
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(render_mobile_html(payload))
        jpath = os.path.splitext(path)[0] + ".json"
        with open(jpath, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning("Mobile digest write failed (%s): %s", path, e)
        return None
    logger.debug("Wrote mobile digest: %s", path)
    return path
