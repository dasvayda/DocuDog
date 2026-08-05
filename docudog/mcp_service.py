"""Read-only DocuDog corpus API for MCP / CLI (no daemon required)."""

from __future__ import annotations

import json
import os
import re
from typing import Any

from . import mobile_digest, semantic_diff, status_dashboard
from .config_loader import load_app_config
from .paths_util import is_unc_path, normalize_fs_path
from .security_labels import format_security_level

_LEVEL_RANK = {"P4": 0, "P3": 1, "P2": 2, "P1": 3}


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
        paths = self.cfg.get("paths") or {}
        raw = str(
            paths.get("state_path")
            or os.path.join("%USERPROFILE%", "Documents", "DocuDog_state.json")
        )
        return normalize_fs_path(os.path.expandvars(raw))

    def report_path(self) -> str:
        paths = self.cfg.get("paths") or {}
        raw = str(
            paths.get("report_path")
            or os.path.join(
                "%USERPROFILE%", "Documents", "classification_report.md"
            )
        )
        return normalize_fs_path(os.path.expandvars(raw))

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
        return {
            "state_path": self.state_path(),
            "report_path": report,
            "status_markdown": md,
            "digest": payload,
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
    ) -> dict[str, Any]:
        state = self.load_state()
        files = state.get("files") if isinstance(state.get("files"), dict) else {}
        level_u = level.strip().upper()
        tag_q = tag.strip().casefold()
        cat_q = category_id.strip()
        q = query.strip()
        cre: re.Pattern[str] | None = None
        if q and regex:
            cre = re.compile(q, re.I)
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
            blob = f"{path}\n{meta.get('summary') or ''}\n{tag_join}\n{' '.join(cats)}"
            if q:
                if cre is not None:
                    if not cre.search(blob):
                        continue
                elif q.casefold() not in blob.casefold():
                    continue
            hits.append(self._file_row(path, meta))
        hits.sort(key=lambda r: r.get("last_analyzed_utc") or "", reverse=True)
        lim = max(1, min(100, int(limit)))
        return {
            "match_count": len(hits),
            "showing": min(lim, len(hits)),
            "results": hits[:lim],
        }

    def get(self, path: str, *, include_excerpt: bool = False) -> dict[str, Any]:
        state = self.load_state()
        files = state.get("files") if isinstance(state.get("files"), dict) else {}
        norm = normalize_fs_path(path)
        meta = files.get(norm)
        if meta is None:
            # case-insensitive / slash variants
            for p, m in files.items():
                if os.path.normcase(normalize_fs_path(p)) == os.path.normcase(norm):
                    norm, meta = p, m
                    break
        if not isinstance(meta, dict):
            return {"ok": False, "error": "not_found_in_state", "path": path}
        row = self._file_row(norm, meta)
        row["ok"] = True
        row["summary_history"] = list(meta.get("summary_history") or [])[-5:]
        row["in_allowlist"] = self.path_allowed(norm)
        if include_excerpt:
            if not row["in_allowlist"]:
                row["excerpt"] = None
                row["excerpt_denied"] = "path_not_in_allowlist"
            else:
                sec = str(meta.get("security_level") or "")
                if not self.excerpt_allowed(sec):
                    row["excerpt"] = None
                    row["excerpt_denied"] = (
                        f"security_level {sec} exceeds "
                        f"max_security_level_for_excerpt={self.max_excerpt_level()}"
                    )
                elif not os.path.isfile(norm):
                    row["excerpt"] = None
                    row["excerpt_denied"] = "file_missing_on_disk"
                else:
                    try:
                        from .router import extract_document_text

                        text, skip = extract_document_text(norm, self.cfg)
                        if skip or not text:
                            row["excerpt"] = None
                            row["excerpt_denied"] = skip or "empty"
                        else:
                            max_c = int(
                                self.mcp_settings().get("max_excerpt_chars", 1200)
                            )
                            row["excerpt"] = text[: max(0, max_c)]
                            row["excerpt_denied"] = None
                    except Exception as e:
                        row["excerpt"] = None
                        row["excerpt_denied"] = str(e)
        return row

    def last_classify(self) -> dict[str, Any]:
        from . import last_classify as lc

        path = lc.resolve_last_classify_path(self.cfg, self.report_path())
        if not os.path.isfile(path):
            return {"ok": False, "error": "missing", "path": path}
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
