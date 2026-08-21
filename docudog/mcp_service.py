"""Read-only DocuDog corpus API for MCP / CLI (no daemon required)."""

from __future__ import annotations

import json
import os
import re
from base64 import b64decode, b64encode
from typing import Any

from . import mobile_digest, semantic_diff, status_dashboard
from .config_loader import load_app_config
from . import artifact_home
from .paths_util import is_unc_path, normalize_fs_path
from .security_labels import format_security_level

_LEVEL_RANK = {"P4": 0, "P3": 1, "P2": 2, "P1": 3}
_MAX_PAGE_SIZE = 100


def _error(code: str, message: str, **fields: Any) -> dict[str, Any]:
    """Return the stable MCP error envelope used by every service method."""
    return {"ok": False, "code": code, "error": message, **fields}


def _page_args(limit: int, offset: int, cursor: str) -> tuple[int, int, dict[str, Any] | None]:
    try:
        lim = int(limit)
    except (TypeError, ValueError):
        return 0, 0, _error("invalid_limit", "limit must be an integer")
    if lim < 1 or lim > _MAX_PAGE_SIZE:
        return 0, 0, _error(
            "invalid_limit", f"limit must be between 1 and {_MAX_PAGE_SIZE}"
        )
    try:
        off = int(offset)
    except (TypeError, ValueError):
        return 0, 0, _error("invalid_offset", "offset must be a non-negative integer")
    if off < 0:
        return 0, 0, _error("invalid_offset", "offset must be a non-negative integer")
    token = str(cursor or "").strip()
    if token:
        try:
            decoded = b64decode(token.encode("ascii"), validate=True).decode("ascii")
            if not decoded.startswith("docudog:"):
                raise ValueError
            cursor_offset = int(decoded.split(":", 1)[1])
        except (ValueError, UnicodeDecodeError, UnicodeEncodeError):
            return 0, 0, _error("invalid_cursor", "cursor is not a valid DocuDog search cursor")
        if cursor_offset < 0:
            return 0, 0, _error("invalid_cursor", "cursor offset must be non-negative")
        if offset:
            return 0, 0, _error("pagination_conflict", "use either cursor or offset, not both")
        off = cursor_offset
    return lim, off, None


def _next_cursor(offset: int) -> str:
    raw = f"docudog:{offset}".encode("ascii")
    return b64encode(raw).decode("ascii")


def _rank(level: str) -> int:
    return _LEVEL_RANK.get(str(level or "").strip().upper(), -1)


class McpService:
    """Load config + state once per call batch; expose search/status/get helpers."""

    def __init__(self, config_dir: str | None = None) -> None:
        self.root = os.path.normpath(
            config_dir or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        )
        self.cfg = load_app_config(self.root)
        self._state: dict[str, Any] | None = None
        self._state_mtime: float | None = None

    def mcp_settings(self) -> dict[str, Any]:
        raw = self.cfg.get("mcp_settings")
        return raw if isinstance(raw, dict) else {}

    def state_path(self) -> str:
        return artifact_home.resolve_state_path(self.cfg)

    def report_path(self) -> str:
        return artifact_home.resolve_report_path(self.cfg)

    def allowlist_roots(self) -> list[str]:
        ms = self.mcp_settings()
        extra = ms.get("extra_allow_directories")
        roots: list[str] = []
        watch = self.cfg.get("watch_settings") or {}
        for d in watch.get("target_directories") or []:
            roots.append(normalize_fs_path(os.path.expandvars(str(d))))
        if isinstance(extra, list):
            for d in extra:
                roots.append(normalize_fs_path(os.path.expandvars(str(d))))
        # always allow state/report parent (outputs)
        for p in (self.state_path(), self.report_path()):
            parent = os.path.dirname(p)
            if parent:
                roots.append(parent)
        # dedupe
        out: list[str] = []
        seen: set[str] = set()
        for r in roots:
            key = os.path.normcase(r)
            if key in seen:
                continue
            seen.add(key)
            out.append(r)
        return out

    def path_allowed(self, path: str) -> bool:
        ms = self.mcp_settings()
        if ms.get("enforce_allowlist") is False:
            return True
        norm = normalize_fs_path(path)
        roots = self.allowlist_roots()
        if not roots:
            return True
        for root in roots:
            try:
                if os.path.commonpath([norm, root]) == root:
                    return True
            except ValueError:
                # different drives
                if os.path.normcase(norm).startswith(os.path.normcase(root)):
                    return True
        return False

    def load_state(self, *, force: bool = False) -> dict[str, Any]:
        path = self.state_path()
        try:
            mtime = os.path.getmtime(path) if os.path.isfile(path) else None
        except OSError:
            mtime = None
        if (
            not force
            and self._state is not None
            and self._state_mtime is not None
            and mtime == self._state_mtime
        ):
            return self._state
        if not os.path.isfile(path):
            self._state = {"files": {}}
            self._state_mtime = mtime
            return self._state
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {"files": {}}
        self._state = data
        self._state_mtime = mtime
        return data

    def max_excerpt_level(self) -> str:
        ms = self.mcp_settings()
        raw = str(ms.get("max_security_level_for_excerpt") or "P4").strip().upper()
        return raw if raw in _LEVEL_RANK else "P4"

    def excerpt_allowed(self, security_level: str) -> bool:
        return _rank(security_level) <= _rank(self.max_excerpt_level()) and _rank(
            security_level
        ) >= 0

    def _file_row(self, path: str, meta: dict[str, Any]) -> dict[str, Any]:
        tags = meta.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        sec = str(meta.get("security_level") or "")
        return {
            "path": path,
            "file_id": str(meta.get("file_id") or ""),
            "basename": os.path.basename(path),
            "security_level": sec,
            "security_label": format_security_level(sec, self.cfg),
            "tags": list(tags),
            "category_ids": list(meta.get("category_ids") or []),
            "summary": str(meta.get("summary") or ""),
            "last_analyzed_utc": str(meta.get("last_analyzed_utc") or ""),
            "last_change_summary": str(meta.get("last_change_summary") or ""),
            "related_paths": list(meta.get("related_paths") or [])[:8],
            "inference_source": str(meta.get("inference_source") or ""),
            "sha256_prefix": str(meta.get("sha256") or "")[:16],
        }

    def status(self) -> dict[str, Any]:
        state = self.load_state()
        report = self.report_path()
        md = status_dashboard.build_status_markdown(self.cfg, state, report)
        # keep MCP payload short
        if len(md) > 6000:
            md = md[:6000] + "\n\n…(truncated)"
        payload = mobile_digest.build_mobile_payload(self.cfg, state, report)
        from . import threads as threads_mod

        thread_rows = state.get("threads") if isinstance(state.get("threads"), list) else []
        payload["threads_top"] = threads_mod.threads_top_payload(thread_rows, limit=8)
        return {
            "state_path": self.state_path(),
            "report_path": report,
            "status_markdown": md,
            "digest": payload,
            "threads_top": payload["threads_top"],
            "allowlist_roots": self.allowlist_roots(),
        }

    def search(
        self,
        *,
        query: str = "",
        level: str = "",
        tag: str = "",
        category_id: str = "",
        limit: int = 20,
        regex: bool = False,
        since: str = "",
        until: str = "",
        offset: int = 0,
        cursor: str = "",
    ) -> dict[str, Any]:
        lim, off, page_error = _page_args(limit, offset, cursor)
        if page_error is not None:
            return page_error
        state = self.load_state()
        files = state.get("files") if isinstance(state.get("files"), dict) else {}
        level_u = level.strip().upper()
        tag_q = tag.strip().casefold()
        cat_q = category_id.strip()
        q = query.strip()
        cre: re.Pattern[str] | None = None
        if q and regex:
            try:
                cre = re.compile(q, re.I)
            except re.error as e:
                return _error("invalid_regex", f"query is not valid regex: {e}")
        hits: list[dict[str, Any]] = []
        for path, meta in files.items():
            if not isinstance(meta, dict):
                continue
            if self.mcp_settings().get("enforce_allowlist", True) and not self.path_allowed(
                path
            ):
                continue
            sec = str(meta.get("security_level") or "").upper()
            if level_u and sec != level_u:
                continue
            tags = meta.get("tags") or []
            if isinstance(tags, str):
                tags = [tags]
            tag_join = ", ".join(str(t) for t in tags)
            if tag_q and tag_q not in tag_join.casefold():
                continue
            cats = [str(c) for c in (meta.get("category_ids") or [])]
            if cat_q and cat_q not in cats:
                continue
            day = str(meta.get("last_analyzed_utc") or "")[:10]
            if since.strip() and day and day < since.strip()[:10]:
                continue
            if until.strip() and day and day > until.strip()[:10]:
                continue
            blob = f"{path}\n{meta.get('summary') or ''}\n{tag_join}\n{' '.join(cats)}"
            if q:
                if cre is not None:
                    if not cre.search(blob):
                        continue
                elif q.casefold() not in blob.casefold():
                    continue
            hits.append(self._file_row(path, meta))
        hits.sort(key=lambda r: r.get("last_analyzed_utc") or "", reverse=True)
        page = hits[off : off + lim]
        next_offset = off + len(page)
        has_more = next_offset < len(hits)
        return {
            "ok": True,
            "match_count": len(hits),
            "offset": off,
            "limit": lim,
            "showing": len(page),
            "has_more": has_more,
            "next_cursor": _next_cursor(next_offset) if has_more else None,
            "results": page,
        }

    def get(
        self,
        path: str = "",
        *,
        file_id: str = "",
        include_excerpt: bool = False,
    ) -> dict[str, Any]:
        state = self.load_state()
        files = state.get("files") if isinstance(state.get("files"), dict) else {}
        if not files:
            return _error("state_empty", "no classified files in state", path=path)
        norm = ""
        meta: Any = None
        fid = (file_id or "").strip()
        if fid:
            from . import file_ids as file_ids_mod

            found = file_ids_mod.find_path_by_file_id(files, fid)
            if found is not None:
                norm, meta = found, files.get(found)
        if not isinstance(meta, dict) and (path or "").strip():
            norm = normalize_fs_path(path)
            meta = files.get(norm)
            if meta is None:
                for p, m in files.items():
                    if os.path.normcase(normalize_fs_path(p)) == os.path.normcase(norm):
                        norm, meta = p, m
                        break
        if not isinstance(meta, dict):
            return _error(
                "not_found_in_state",
                "file was not found in DocuDog state",
                path=path,
                file_id=fid,
            )
        row = self._file_row(norm, meta)
        row["ok"] = True
        row["summary_history"] = list(meta.get("summary_history") or [])[-5:]
        row["in_allowlist"] = self.path_allowed(norm)
        sha = str(meta.get("sha256") or "")
        row["sha256"] = sha
        if include_excerpt:
            if not row["in_allowlist"]:
                row["excerpt"] = None
                row["excerpt_denied"] = "path_not_in_allowlist"
                row["code"] = "path_denied"
            else:
                sec = str(meta.get("security_level") or "")
                if not self.excerpt_allowed(sec):
                    row["excerpt"] = None
                    row["excerpt_denied"] = (
                        f"security_level {sec} exceeds "
                        f"max_security_level_for_excerpt={self.max_excerpt_level()}"
                    )
                    row["code"] = (
                        "excerpt_blocked_p1"
                        if str(sec).upper() in ("P1", "P2")
                        else "excerpt_blocked"
                    )
                elif not os.path.isfile(norm):
                    row["excerpt"] = None
                    row["excerpt_denied"] = "file_missing_on_disk"
                    row["code"] = "file_missing"
                else:
                    try:
                        from .router import extract_document_text

                        text, skip = extract_document_text(norm, self.cfg)
                        if skip or not text:
                            row["excerpt"] = None
                            row["excerpt_denied"] = skip or "empty"
                            row["truncated"] = False
                        else:
                            max_c = int(
                                self.mcp_settings().get("max_excerpt_chars", 1200)
                            )
                            max_c = max(0, max_c)
                            row["excerpt"] = text[:max_c]
                            row["truncated"] = len(text) > max_c
                            row["excerpt_denied"] = None
                    except Exception as e:
                        row["excerpt"] = None
                        row["excerpt_denied"] = str(e)
                        row["code"] = "excerpt_error"
        return row

    def by_hash(self, sha256: str, *, limit: int = 20) -> dict[str, Any]:
        needle = str(sha256 or "").strip().lower()
        if len(needle) < 8:
            return _error("hash_too_short", "need at least 8 hex chars")
        if not re.fullmatch(r"[0-9a-f]+", needle):
            return _error("invalid_hash", "sha256 must contain hexadecimal characters")
        lim, _off, page_error = _page_args(limit, 0, "")
        if page_error is not None:
            return page_error
        state = self.load_state()
        files = state.get("files") if isinstance(state.get("files"), dict) else {}
        hits: list[dict[str, Any]] = []
        for path, meta in files.items():
            if not isinstance(meta, dict):
                continue
            full = str(meta.get("sha256") or "").lower()
            if not full.startswith(needle) and full != needle:
                continue
            if self.mcp_settings().get("enforce_allowlist", True) and not self.path_allowed(
                path
            ):
                continue
            hits.append(self._file_row(path, meta))
        return {"ok": True, "match_count": len(hits), "results": hits[:lim]}

    def thread(
        self,
        thread_id: str = "",
        path: str = "",
        file_id: str = "",
    ) -> dict[str, Any]:
        state = self.load_state()
        from . import threads as threads_mod

        rows = state.get("threads") if isinstance(state.get("threads"), list) else []
        got = threads_mod.find_thread(
            rows, thread_id=thread_id, path=path, file_id=file_id
        )
        if got is None and (path or file_id):
            resolved = self.get(path=path, file_id=file_id)
            if resolved.get("ok"):
                got = threads_mod.find_thread(
                    rows,
                    path=str(resolved.get("path") or ""),
                    file_id=str(resolved.get("file_id") or ""),
                )
        if got is None:
            return _error(
                "thread_not_found",
                "thread was not found",
                thread_id=thread_id,
                path=path,
                file_id=file_id,
            )
        return {"ok": True, "thread": got}

    def get_lineage(self, path: str = "", file_id: str = "") -> dict[str, Any]:
        state = self.load_state()
        from . import threads as threads_mod

        rows = state.get("threads") if isinstance(state.get("threads"), list) else []
        if not rows:
            threads_mod.refresh_threads(self.cfg, state)
            rows = state.get("threads") if isinstance(state.get("threads"), list) else []
        th = threads_mod.find_thread(rows, path=path, file_id=file_id)
        if th is None:
            resolved = self.get(path=path, file_id=file_id)
            if resolved.get("ok"):
                th = threads_mod.find_thread(
                    rows,
                    path=str(resolved.get("path") or ""),
                    file_id=str(resolved.get("file_id") or ""),
                )
        if th is None:
            return _error(
                "lineage_not_found",
                "no version/conversation thread for this file",
                path=path,
                file_id=file_id,
            )
        members = list(th.get("members") or [])
        files = state.get("files") if isinstance(state.get("files"), dict) else {}

        def _meta_for(path: str) -> dict[str, Any]:
            m = files.get(path)
            if isinstance(m, dict):
                return m
            want = os.path.normcase(path)
            for fp, fm in files.items():
                if os.path.normcase(fp) == want and isinstance(fm, dict):
                    return fm
            return {}

        changes: list[dict[str, Any]] = []
        for m in members:
            if not isinstance(m, dict):
                continue
            p = str(m.get("path") or "")
            meta = _meta_for(p)
            changes.append(
                {
                    "path": p,
                    "basename": m.get("basename"),
                    "summary": m.get("summary"),
                    "utc": m.get("utc"),
                    "last_change_summary": meta.get("last_change_summary") or "",
                }
            )
        latest_change = ""
        if changes:
            latest_change = str(changes[0].get("last_change_summary") or "")
        return {
            "ok": True,
            "latest_path": th.get("latest_path"),
            "latest_file_id": th.get("latest_file_id"),
            "title": th.get("title"),
            "kind": th.get("kind"),
            "thread_id": th.get("id"),
            "one_liner": th.get("one_liner") or latest_change,
            "last_change_summary": latest_change,
            "members": changes,
        }

    def get_context_bundle(self, path: str = "", file_id: str = "") -> dict[str, Any]:
        resolved = self.get(path=path, file_id=file_id)
        if not resolved.get("ok"):
            return resolved
        anchor = str(resolved.get("path") or "")
        state = self.load_state()
        bundles_out: list[dict[str, Any]] = []
        raw = state.get("context_bundles")
        if isinstance(raw, list):
            for b in raw:
                if not isinstance(b, dict):
                    continue
                rel = [str(x) for x in (b.get("related_paths") or [])]
                if os.path.normcase(str(b.get("anchor_path") or "")) == os.path.normcase(
                    anchor
                ) or any(
                    os.path.normcase(p) == os.path.normcase(anchor) for p in rel
                ):
                    bundles_out.append(b)
        related = self.related(anchor, limit=8)
        return {
            "ok": True,
            "anchor": anchor,
            "related_paths": resolved.get("related_paths") or [],
            "related": related.get("related") if related.get("ok") else [],
            "context_bundles": bundles_out[:8],
        }

    def last_classify(self) -> dict[str, Any]:
        from . import last_classify as lc

        path = lc.resolve_last_classify_path(self.cfg, self.report_path())
        if not os.path.isfile(path):
            return _error("not_found", "last classification file is missing", path=path)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {"ok": True, "path": path, "data": data}

    def recent_changes(self, *, limit: int = 10) -> dict[str, Any]:
        state = self.load_state()
        rows = semantic_diff.recent_changes_from_state(state, limit=limit)
        return {"count": len(rows), "changes": rows}

    def related(self, path: str, *, limit: int = 5) -> dict[str, Any]:
        state = self.load_state()
        files = state.get("files") if isinstance(state.get("files"), dict) else {}
        got = self.get(path)
        if not got.get("ok"):
            return got
        meta = files.get(got["path"]) or {}
        from . import related_docs

        paths = related_docs.find_related_paths(
            state, got["path"], meta if isinstance(meta, dict) else {}, max_n=limit
        )
        return {
            "ok": True,
            "anchor": got["path"],
            "related": [self.get(p) for p in paths],
        }

    def ping(self) -> dict[str, Any]:
        sp = self.state_path()
        return {
            "ok": True,
            "service": "docudog",
            "config_dir": self.root,
            "state_path": sp,
            "state_exists": os.path.isfile(sp),
            "unc_state": is_unc_path(sp),
            "mcp_settings": {
                "enforce_allowlist": self.mcp_settings().get("enforce_allowlist", True),
                "max_security_level_for_excerpt": self.max_excerpt_level(),
            },
        }
