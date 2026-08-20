"""Inbox-style document threads (version + conversation) for status + MCP."""

from __future__ import annotations

import hashlib
import html
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from . import file_ids
from .lineage import _build_multi_groups, lineage_group_key
from .security_labels import format_security_level

logger = logging.getLogger(__name__)

_LEVEL_RANK = {"P4": 1, "P3": 2, "P2": 3, "P1": 4}
_THREADS_H2 = "최근 대화"


def _utc_day(iso: str) -> str:
    return (iso or "").strip()[:10]


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _meta_utc(meta: dict[str, Any]) -> str:
    return str(meta.get("last_analyzed_utc") or meta.get("last_checked_utc") or "")


def _watch_roots(cfg: dict[str, Any]) -> list[str]:
    watch = cfg.get("watch_settings") or {}
    out: list[str] = []
    for d in watch.get("target_directories") or []:
        s = os.path.normpath(os.path.expandvars(str(d)))
        out.append(s)
    return out


def _parent_rel_parts(path: str, roots: list[str]) -> int | None:
    """How many directory parts sit under the matching watch root (file's parent)."""
    parent = os.path.dirname(os.path.normpath(path))
    try:
        parent_abs = os.path.abspath(parent)
    except OSError:
        parent_abs = parent
    best: int | None = None
    for root in roots:
        try:
            root_abs = os.path.abspath(os.path.normpath(root))
        except OSError:
            root_abs = os.path.normpath(root)
        try:
            common = os.path.commonpath([parent_abs, root_abs])
        except ValueError:
            continue
        if os.path.normcase(common) != os.path.normcase(root_abs):
            continue
        rel = os.path.relpath(parent_abs, root_abs)
        if rel in (".", ""):
            n = 0
        else:
            n = len([p for p in rel.split(os.sep) if p and p != "."])
        if best is None or n < best:
            best = n
    return best


def _tag_set(meta: dict[str, Any]) -> set[str]:
    tags = meta.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    return {str(t).strip().casefold() for t in tags if str(t).strip()}


def _folder_qualifies(
    folder_paths: list[str],
    files: dict[str, Any],
    state: dict[str, Any],
) -> bool:
    keys = {lineage_group_key(os.path.basename(p)) for p in folder_paths}
    if len(keys) < 2:
        return False
    tag_counts: dict[str, int] = {}
    for p in folder_paths:
        meta = files.get(p)
        if not isinstance(meta, dict):
            continue
        for t in _tag_set(meta):
            tag_counts[t] = tag_counts.get(t, 0) + 1
    if any(n >= 2 for n in tag_counts.values()):
        return True
    bundles = state.get("context_bundles")
    if not isinstance(bundles, list):
        return False
    folder_set = {os.path.normcase(p) for p in folder_paths}
    for b in bundles:
        if not isinstance(b, dict):
            continue
        hit = 0
        for raw in [b.get("anchor_path"), *(b.get("related_paths") or [])]:
            if os.path.normcase(str(raw or "")) in folder_set:
                hit += 1
        if hit >= 2:
            return True
    return False


def _max_security(members_meta: list[dict[str, Any]]) -> str:
    best = ""
    best_r = 0
    for meta in members_meta:
        sec = str(meta.get("security_level") or "").upper()
        r = _LEVEL_RANK.get(sec, 0)
        if r > best_r:
            best_r = r
            best = sec
    return best


def _member_dict(
    path: str,
    meta: dict[str, Any],
    role: str,
) -> dict[str, Any]:
    sha = str(meta.get("sha256") or "")
    one = str(meta.get("last_change_summary") or meta.get("summary") or "").strip()
    if len(one) > 160:
        one = one[:157] + "..."
    return {
        "path": path,
        "file_id": str(meta.get("file_id") or ""),
        "sha12": sha[:12],
        "utc": _meta_utc(meta),
        "summary": one,
        "security_level": str(meta.get("security_level") or ""),
        "role": role,
        "basename": os.path.basename(path),
    }


def _sort_newest_first(
    items: list[tuple[str, dict[str, Any]]],
) -> list[tuple[str, dict[str, Any]]]:
    return sorted(items, key=lambda pm: _meta_utc(pm[1]), reverse=True)


def _conv_id(folder: str) -> str:
    key = os.path.normcase(os.path.normpath(folder))
    digest = hashlib.sha256(key.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"conv:{digest}"


def _ver_id(group_key: str) -> str:
    safe = re.sub(r"\s+", "_", group_key.strip())[:80]
    return f"ver:{safe}"


def build_threads(state: dict[str, Any], cfg: dict[str, Any] | None) -> list[dict[str, Any]]:
    cfg = cfg or {}
    ts = file_ids.thread_settings(cfg)
    if not ts["enabled"]:
        return []
    files = state.get("files") if isinstance(state.get("files"), dict) else {}
    rows: list[tuple[str, dict[str, Any]]] = []
    for path, meta in files.items():
        if isinstance(meta, dict) and meta.get("sha256"):
            rows.append((path, meta))
    if len(rows) < 2:
        return []

    multi, _singletons, _note = _build_multi_groups(rows, cfg)
    path_to_ver: dict[str, str] = {}
    version_groups: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for gk, members in multi:
        version_groups[gk] = members
        for p, _m in members:
            path_to_ver[p] = gk

    used_in_conv: set[str] = set()
    threads: list[dict[str, Any]] = []
    today = _today_utc()
    max_members = ts["max_members"]
    roots = _watch_roots(cfg)

    if ts["include_conversations"] and roots:
        by_folder: dict[str, list[str]] = {}
        for path, _meta in rows:
            depth = _parent_rel_parts(path, roots)
            if depth is None or depth < ts["min_rel_depth"]:
                continue
            folder = os.path.dirname(os.path.normpath(path))
            by_folder.setdefault(folder, []).append(path)

        for folder, paths in by_folder.items():
            if len(paths) < 2:
                continue
            if not _folder_qualifies(paths, files, state):
                continue
            items = [(p, files[p]) for p in paths if isinstance(files.get(p), dict)]
            items = _sort_newest_first(items)[:max_members]
            if len(items) < 2:
                continue
            latest_path, latest_meta = items[0]
            members: list[dict[str, Any]] = []
            ver_in_folder = False
            for i, (p, m) in enumerate(items):
                in_ver = p in path_to_ver
                if in_ver:
                    ver_in_folder = True
                if i == 0:
                    role = "latest"
                elif in_ver:
                    role = "version"
                else:
                    role = "peer"
                members.append(_member_dict(p, m, role))
                used_in_conv.add(p)
            kind = "mixed" if ver_in_folder else "conversation"
            threads.append(
                {
                    "id": _conv_id(folder),
                    "kind": kind,
                    "title": os.path.basename(folder) or folder,
                    "folder": folder,
                    "latest_path": latest_path,
                    "latest_file_id": str(latest_meta.get("file_id") or ""),
                    "last_utc": _meta_utc(latest_meta),
                    "member_count": len(members),
                    "today_n": sum(1 for mem in members if _utc_day(str(mem.get("utc"))) == today),
                    "max_security": _max_security([m for _, m in items]),
                    "one_liner": members[0].get("summary") if members else "",
                    "members": members,
                }
            )

    for gk, members in version_groups.items():
        if all(p in used_in_conv for p, _m in members):
            continue
        items = _sort_newest_first(list(members))[:max_members]
        if len(items) < 2:
            continue
        latest_path, latest_meta = items[0]
        out_members = [
            _member_dict(p, m, "latest" if i == 0 else "version")
            for i, (p, m) in enumerate(items)
        ]
        threads.append(
            {
                "id": _ver_id(gk),
                "kind": "version",
                "title": gk,
                "latest_path": latest_path,
                "latest_file_id": str(latest_meta.get("file_id") or ""),
                "last_utc": _meta_utc(latest_meta),
                "member_count": len(out_members),
                "today_n": sum(
                    1 for mem in out_members if _utc_day(str(mem.get("utc"))) == today
                ),
                "max_security": _max_security([m for _, m in items]),
                "one_liner": out_members[0].get("summary") if out_members else "",
                "members": out_members,
            }
        )

    threads.sort(key=lambda t: str(t.get("last_utc") or ""), reverse=True)
    return threads[: ts["max_threads"]]


def refresh_threads(cfg: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    file_ids.ensure_all_file_ids(state)
    threads = build_threads(state, cfg)
    state["threads"] = threads
    return threads


def format_threads_markdown(
    cfg: dict[str, Any],
    threads: list[dict[str, Any]],
) -> str:
    ts = file_ids.thread_settings(cfg)
    header_n = ts["header_limit"]
    unfold = ts["unfold_members"]
    if not threads:
        return ""
    lines = [f"## {_THREADS_H2}\n\n"]
    for th in threads[:header_n]:
        sec = format_security_level(str(th.get("max_security") or ""), cfg)
        today_bit = f" · 오늘 +{th.get('today_n')}" if int(th.get("today_n") or 0) else ""
        lines.append(
            f"- **{th.get('title')}** ({th.get('member_count')})"
            + (f" · {sec}" if sec else "")
            + today_bit
            + "\n"
        )
        members = list(th.get("members") or [])
        if members:
            top = members[0]
            lines.append(
                f"  - 최신: `{top.get('basename')}`"
                + (f" — {top.get('summary')}" if top.get("summary") else "")
                + "\n"
            )
            prev_names = [str(m.get("basename") or "") for m in members[1:unfold]]
            if prev_names:
                lines.append(f"  - 이전: {' · '.join(f'`{n}`' for n in prev_names)}\n")
    lines.append("\n")
    return "".join(lines)


def format_threads_html(
    cfg: dict[str, Any],
    threads: list[dict[str, Any]],
) -> str:
    ts = file_ids.thread_settings(cfg)
    header_n = ts["header_limit"]
    unfold = ts["unfold_members"]
    if not threads:
        return ""
    parts = [f"<h2>{html.escape(_THREADS_H2)}</h2>"]
    for th in threads[:header_n]:
        sec = format_security_level(str(th.get("max_security") or ""), cfg)
        today_n = int(th.get("today_n") or 0)
        today_bit = f" · 오늘 +{today_n}" if today_n else ""
        summary = (
            f"<strong>{html.escape(str(th.get('title') or ''))}</strong> "
            f"({th.get('member_count')})"
            + (f" · {html.escape(sec)}" if sec else "")
            + html.escape(today_bit)
        )
        members = list(th.get("members") or [])[:unfold]
        lis: list[str] = []
        for i, m in enumerate(members):
            label = "최신" if i == 0 else "이전"
            line = f"{label}: <code>{html.escape(str(m.get('basename') or ''))}</code>"
            if m.get("summary"):
                line += f" — {html.escape(str(m.get('summary')))}"
            lis.append(f"<li>{line}</li>")
        inner = "<ul>\n" + "\n".join(lis) + "\n</ul>" if lis else ""
        parts.append(
            f'<details class="thread"><summary>{summary}</summary>\n{inner}\n</details>'
        )
    return "\n".join(parts)


def inject_threads_html(page_html: str, section_html: str) -> str:
    if not section_html:
        return page_html
    pattern = re.compile(
        rf"<h2>\s*{re.escape(_THREADS_H2)}\s*</h2>.*?(?=<h2>|</main>)",
        re.DOTALL | re.IGNORECASE,
    )
    if pattern.search(page_html):
        return pattern.sub(section_html + "\n", page_html, count=1)
    return page_html.replace("</main>", section_html + "\n</main>", 1)


def threads_top_payload(threads: list[dict[str, Any]], *, limit: int = 8) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for th in threads[: max(1, limit)]:
        out.append(
            {
                "id": th.get("id"),
                "kind": th.get("kind"),
                "title": th.get("title"),
                "latest": os.path.basename(str(th.get("latest_path") or "")),
                "latest_path": th.get("latest_path"),
                "count": th.get("member_count"),
                "today_n": th.get("today_n"),
                "max_security": th.get("max_security"),
            }
        )
    return out


def find_thread(
    threads: list[dict[str, Any]],
    *,
    thread_id: str = "",
    path: str = "",
    file_id: str = "",
) -> dict[str, Any] | None:
    tid = (thread_id or "").strip()
    if tid:
        for th in threads:
            if str(th.get("id") or "") == tid:
                return th
    fid = (file_id or "").strip()
    np = os.path.normcase(os.path.normpath(path)) if path else ""
    for th in threads:
        for m in th.get("members") or []:
            if not isinstance(m, dict):
                continue
            if fid and str(m.get("file_id") or "") == fid:
                return th
            if np and os.path.normcase(os.path.normpath(str(m.get("path") or ""))) == np:
                return th
    return None
