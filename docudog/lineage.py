"""
Semantic Lineage — filename variants (copy suffixes) plus optional **similarity clustering**
(filename stem + summary Jaccard) to group human "fragmented save" patterns into one lineage.

No external Git library; uses difflib + lightweight token overlap. Aligns with master-plan
Shadow Git / DNA map direction at MVP depth.
"""

from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from . import inference
from .reporter import _format_report_timestamp

logger = logging.getLogger(__name__)

# Filename normalization: strip common duplicate suffixes before extension.
_RE_WIN_COPY_PAREN = re.compile(r"\s*\(\d+\)\s*$", re.IGNORECASE)
_RE_COPY_EN = re.compile(r"\s*-\s*copy\s*$", re.IGNORECASE)
_RE_COPY_KO = re.compile(r"\s*-\s*복사본\s*$", re.IGNORECASE)
# Aggressive stem normalization for similarity (제안서_v1 / 제안서_최종_수정 / ...).
_RE_TRAILING_VER = re.compile(
    r"[_\s.-]+(?:v|ver|version|r)[.\s_-]?\d+\s*$", re.IGNORECASE
)
_RE_TRAILING_LABEL = re.compile(
    r"[_\s.-]+(?:final|draft|complete|done|edit|"
    r"최종|최종본|수정|수정본|완료|임시|제안|본안|확정|편집)\d*\s*$",
    re.IGNORECASE,
)
_RE_TRAILING_NUM = re.compile(r"[_\s.-]+\d{1,4}\s*$")


def lineage_group_key(filename: str) -> str:
    """Stable key so `report (1).xlsx` and `report (2).xlsx` cluster together."""
    base, ext = os.path.splitext(filename.strip())
    s = _RE_WIN_COPY_PAREN.sub("", base)
    s = _RE_COPY_EN.sub("", s)
    s = _RE_COPY_KO.sub("", s)
    return f"{s}{ext}".lower()


class _UnionFind:
    __slots__ = ("parent", "rank")

    def __init__(self, n: int) -> None:
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        p = self.parent
        while p[x] != x:
            p[x] = p[p[x]]
            x = p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        rank = self.rank
        p = self.parent
        if rank[ra] < rank[rb]:
            p[ra] = rb
        elif rank[ra] > rank[rb]:
            p[rb] = ra
        else:
            p[rb] = ra
            rank[ra] += 1


def _normalize_stem_similarity(stem: str) -> str:
    """Stem for difflib: strip version / final-style / short numeric tails."""
    s = stem.strip()
    s = _RE_WIN_COPY_PAREN.sub("", s)
    s = _RE_COPY_EN.sub("", s)
    s = _RE_COPY_KO.sub("", s)
    for _ in range(6):
        prev = s
        s = _RE_TRAILING_VER.sub("", s)
        s = _RE_TRAILING_LABEL.sub("", s)
        s = _RE_TRAILING_NUM.sub("", s)
        if prev == s:
            break
    s = re.sub(r"[_\s.-]+", "_", s.strip(" _.-"))
    return s.lower()


def _tokens_from_summary(text: str) -> set[str]:
    return {
        t
        for t in re.findall(r"[\w가-힣]{2,}", text.lower())
        if len(t) >= 2
    }


def _summary_jaccard(a: str, b: str) -> float:
    ta = _tokens_from_summary(a)
    tb = _tokens_from_summary(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    uni = len(ta | tb)
    return inter / uni if uni else 0.0


def _pair_similarity(
    path_i: str,
    meta_i: dict[str, Any],
    path_j: str,
    meta_j: dict[str, Any],
    w_fn: float,
    w_sum: float,
) -> float:
    bi, ext_i = os.path.splitext(os.path.basename(path_i))
    bj, ext_j = os.path.splitext(os.path.basename(path_j))
    if ext_i.lower() != ext_j.lower():
        return 0.0
    si = _normalize_stem_similarity(bi)
    sj = _normalize_stem_similarity(bj)
    fn_ratio = SequenceMatcher(None, si, sj).ratio()
    summ_i = str(meta_i.get("summary") or "").strip()
    summ_j = str(meta_j.get("summary") or "").strip()
    if summ_i and summ_j:
        jac = _summary_jaccard(summ_i, summ_j)
        return w_fn * fn_ratio + w_sum * jac
    return fn_ratio


def _lineage_clustering_mode(ls: dict[str, Any]) -> str:
    raw = str(ls.get("clustering") or "both").strip().lower()
    if raw in ("filename_key", "filename", "copy_key"):
        return "filename_key"
    if raw in ("similarity", "fuzzy"):
        return "similarity"
    return "both"


def _build_multi_groups(
    rows: list[tuple[str, dict[str, Any]]],
    cfg: dict[str, Any] | None,
) -> tuple[list[tuple[str, list[tuple[str, dict[str, Any]]]]], int, str]:
    """
    Return (multi_groups, num_single_file_components, status_note).
    Each multi group is (group_key, members).
    """
    if len(rows) < 2:
        return [], len(rows), "fewer_than_2_files"

    ls = (cfg or {}).get("lineage_settings") or {}
    if not isinstance(ls, dict):
        ls = {}
    mode = _lineage_clustering_mode(ls)
    thr = float(ls.get("similarity_threshold", 0.58))
    w_fn = float(ls.get("filename_weight", 0.55))
    w_sum = float(ls.get("summary_weight", 0.45))
    tot = w_fn + w_sum
    if tot > 0:
        w_fn, w_sum = w_fn / tot, w_sum / tot
    max_n = int(ls.get("max_files_for_similarity", 400))

    n = len(rows)
    uf = _UnionFind(n)
    by_key: dict[str, list[int]] = defaultdict(list)
    for idx, (path, _meta) in enumerate(rows):
        key = lineage_group_key(os.path.basename(path))
        by_key[key].append(idx)

    if mode in ("filename_key", "both"):
        for indices in by_key.values():
            for k in range(1, len(indices)):
                uf.union(indices[0], indices[k])

    sim_note = ""
    if mode in ("similarity", "both"):
        if n > max_n:
            logger.warning(
                "Lineage similarity skipped: %s files > lineage_settings.max_files_for_similarity=%s",
                n,
                max_n,
            )
            sim_note = f"similarity skipped (file count > {max_n})"
        else:
            edges = 0
            for i in range(n):
                for j in range(i + 1, n):
                    pi, mi = rows[i]
                    pj, mj = rows[j]
                    if _pair_similarity(pi, mi, pj, mj, w_fn, w_sum) >= thr:
                        uf.union(i, j)
                        edges += 1
            sim_note = f"fuzzy merges (score>={thr}): {edges} pair-unions"
            logger.debug("Lineage %s", sim_note)

    if mode == "filename_key":
        sim_note = "clustering=filename_key only"

    components: dict[int, list[int]] = defaultdict(list)
    for idx in range(n):
        components[uf.find(idx)].append(idx)

    multi: list[tuple[str, list[tuple[str, dict[str, Any]]]]] = []
    singletons = 0
    for _root, indices in components.items():
        members = [rows[i] for i in sorted(indices)]
        if len(members) < 2:
            singletons += 1
            continue
        label_path = _sort_members_lineage(list(members))[0][0]
        gk = lineage_group_key(os.path.basename(label_path))
        multi.append((gk, members))

    multi.sort(key=lambda x: (-len(x[1]), x[0]))
    return multi, singletons, sim_note


def _sha_prefix(h: str, n: int = 12) -> str:
    h = h.strip()
    return h[:n] if len(h) >= n else h


def mermaid_safe(s: str, max_len: int = 80) -> str:
    s = s.replace('"', "'").replace("\n", " ").replace("[", "(").replace("]", ")")
    if len(s) > max_len:
        s = s[: max_len - 3] + "..."
    return s


def _tags_cell(meta: dict[str, Any]) -> str:
    tags = meta.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    return ", ".join(str(t) for t in tags[:8])


def _group_description_for_llm(members_sorted: list[tuple[str, dict[str, Any]]]) -> str:
    lines: list[str] = []
    for path, meta in members_sorted:
        summ = str(meta.get("summary", "")).strip().replace("\n", " ")
        if len(summ) > 320:
            summ = summ[:317] + "..."
        lines.append(
            f"- {os.path.basename(path)} | sec={meta.get('security_level', '')} | "
            f"tags={_tags_cell(meta)} | summary_excerpt={summ}"
        )
    return "\n".join(lines)


def _sort_members_lineage(
    members: list[tuple[str, dict[str, Any]]],
) -> list[tuple[str, dict[str, Any]]]:
    """Rough timeline: last_analyzed_utc, then path."""

    def sort_key(item: tuple[str, dict[str, Any]]) -> tuple[str, str]:
        path, meta = item
        ts = str(meta.get("last_analyzed_utc") or meta.get("last_checked_utc") or "")
        return ts, path.lower()

    return sorted(members, key=sort_key)


def _append_context_bundles_section(
    lines: list[str],
    state: dict[str, Any],
    cfg: dict[str, Any] | None,
) -> None:
    if not cfg:
        return
    ls = cfg.get("lineage_settings") or {}
    if not isinstance(ls, dict) or not bool(ls.get("context_bundles_enabled", False)):
        return
    raw = state.get("context_bundles")
    if not isinstance(raw, list) or not raw:
        return
    lines.append("## Context bundles (time-window co-occurrence)")
    lines.append("")
    lines.append(
        "Heuristic groups: other paths whose filesystem events fell within **±N minutes** of the "
        "anchor file’s event time (same folder, or optional `context_bundle_extra_directories`). "
        "Unrelated saves can co-occur."
    )
    lines.append("")
    lines.append("| Bundle | Anchor | Event (UTC) | Window | Related |")
    lines.append("|---|---|---:|---:|---|")
    max_rows = 60
    for b in raw[:max_rows]:
        if not isinstance(b, dict):
            continue
        bid = str(b.get("bundle_id", ""))
        ap = str(b.get("anchor_path", ""))
        ev = str(b.get("anchor_event_utc", ""))
        try:
            wm = int(b.get("window_minutes", 0))
        except (TypeError, ValueError):
            wm = 0
        rel = b.get("related_paths") or []
        if isinstance(rel, list):
            rel_n = len(rel)
            rel_preview = ", ".join(
                mermaid_safe(os.path.basename(str(p)), 60) for p in rel[:6]
            )
            if rel_n > 6:
                rel_preview += f", … (+{rel_n - 6} more)"
        else:
            rel_n = 0
            rel_preview = ""
        lines.append(
            f"| `{mermaid_safe(bid, 14)}` | `{mermaid_safe(os.path.basename(ap), 80)}` | "
            f"{mermaid_safe(ev, 44)} | {wm} min | **{rel_n}:** {rel_preview} |"
        )
    if len(raw) > max_rows:
        lines.append("")
        lines.append(f"_Showing newest {max_rows} of {len(raw)} bundle(s)._")
    lines.append("")


def build_lineage_markdown(state: dict[str, Any], cfg: dict[str, Any] | None = None) -> str:
    files_raw = state.get("files") or {}
    rows: list[tuple[str, dict[str, Any]]] = []
    for path, meta in files_raw.items():
        if not isinstance(meta, dict):
            continue
        h = meta.get("sha256")
        if not h:
            continue
        rows.append((path, meta))

    if not rows:
        lines0: list[str] = [
            "# DocuDog — Document lineage map",
            "",
            "_No tracked files yet — analyze documents and `DocuDog_state.json` will populate this view._",
            "",
        ]
        _append_context_bundles_section(lines0, state, cfg)
        return "\n".join(lines0)

    multi, singletons, sim_note = _build_multi_groups(rows, cfg)

    lines: list[str] = [
        "# DocuDog — Document lineage map",
        "",
        "Virtual **Shadow Git–style** lineage (no `.git` folder): related files are clustered from "
        "**local state** only (path, SHA-256, tags, summary).",
        "",
        "- **Filename key**: strip Windows `(1)`, `(2)`, `- copy`, `복사본`, then group identical keys.",
        "- **Similarity** (`lineage_settings.clustering` = `both` default, or `similarity`): same extension; "
        "stem similarity after stripping `_v1` / `_최종` / `_수정`-style tails (`difflib`); if both sides have "
        "a **summary**, blend in **token Jaccard** overlap. Tune `similarity_threshold` / weights in config.",
        "",
        "Open in VS Code (or GitHub) to render **Mermaid**. Optional LLM one-liners: "
        "`lineage_settings.llm_cluster_hints`.",
        "",
        f"Updated: {_format_report_timestamp(datetime.now(timezone.utc))}",
        "",
        f"- Tracked files with hash: **{len(rows)}**",
        f"- Multi-file lineage groups: **{len(multi)}**",
        f"- Single-file components (not merged): **{singletons}**",
    ]
    if sim_note:
        lines.append(f"- Clustering: _{mermaid_safe(sim_note, 160)}_")
    lines.append("")

    mermaid_lines: list[str] = [
        "```mermaid",
        "flowchart TB",
    ]
    node_i = 0

    for g_idx, (_gkey, members) in enumerate(multi, start=1):
        members_sorted = _sort_members_lineage(list(members))
        unique_hashes = {str(m[1].get("sha256", "")) for m in members_sorted}
        dup_note = "same content" if len(unique_hashes) == 1 else f"{len(unique_hashes)} content variants"
        label0 = os.path.basename(members_sorted[0][0])
        sg_title = mermaid_safe(f"G{g_idx}: {label0} ({len(members_sorted)} files, {dup_note})")
        mermaid_lines.append(f"    subgraph g{g_idx}[\"{sg_title}\"]")

        node_ids: list[str] = []
        for path, meta in members_sorted:
            nid = f"n{node_i}"
            node_i += 1
            node_ids.append(nid)
            bn = mermaid_safe(os.path.basename(path), 60)
            sha = _sha_prefix(str(meta.get("sha256", "")))
            mermaid_lines.append(f"        {nid}[\"{bn}<br/>sha {sha}…\"]")

        for i in range(len(node_ids) - 1):
            a, b = node_ids[i], node_ids[i + 1]
            same = members_sorted[i][1].get("sha256") == members_sorted[i + 1][1].get("sha256")
            link = "---" if same else "-.->"
            mermaid_lines.append(f"        {a} {link} {b}")

        mermaid_lines.append("    end")

    if node_i > 0:
        mermaid_lines.append("```")
        mermaid_lines.append("")
        lines.append("## Lineage graph (multi-file groups)")
        lines.append("")
        lines.extend(mermaid_lines)
    else:
        lines.append("_No multi-file lineage groups yet — duplicate-style names will appear here._")
        lines.append("")

    lines.append("## Detail tables")
    lines.append("")

    for g_idx, (_gkey, members) in enumerate(multi, start=1):
        members_sorted = _sort_members_lineage(list(members))
        label0 = os.path.basename(members_sorted[0][0])
        lines.append(f"### Group {g_idx}: `{label0}` ({len(members_sorted)} files)")
        lines.append("")
        lines.append("| File | SHA-256 (prefix) | Security | Tags | Last analyzed |")
        lines.append("|---|---|---|---|---|")
        for path, meta in members_sorted:
            lines.append(
                f"| `{mermaid_safe(os.path.basename(path), 120)}` | `{_sha_prefix(str(meta.get('sha256', '')), 16)}` | "
                f"{mermaid_safe(str(meta.get('security_level', '')), 20)} | "
                f"{mermaid_safe(_tags_cell(meta), 80)} | "
                f"{mermaid_safe(str(meta.get('last_analyzed_utc', '')), 40)} |"
            )
        lines.append("")

    if not multi:
        lines.append("_No tables — need at least two paths that share a lineage key._")
        lines.append("")

    if cfg and multi:
        ls = cfg.get("lineage_settings") or {}
        if bool(ls.get("llm_cluster_hints", False)):
            max_g = int(ls.get("llm_max_hint_groups", 8))
            batch: list[tuple[int, str]] = []
            for g_idx, (_gkey, members) in enumerate(multi[:max_g], start=1):
                members_sorted = _sort_members_lineage(list(members))
                batch.append((g_idx, _group_description_for_llm(members_sorted)))
            hints_map = inference.lineage_cluster_hints_batch(batch, cfg)
            if hints_map:
                lines.append("## LLM relationship hints")
                lines.append("")
                lines.append(
                    "_One-sentence hypotheses from the local model; filenames/tags/summaries only._"
                )
                lines.append("")
                for g_idx, (_gkey, members) in enumerate(multi[:max_g], start=1):
                    if g_idx not in hints_map:
                        continue
                    label = os.path.basename(_sort_members_lineage(list(members))[0][0])
                    lines.append(
                        f"- **Group {g_idx}** (`{mermaid_safe(label, 120)}`): "
                        f"{mermaid_safe(hints_map[g_idx], 400)}"
                    )
                    lines.append("")

    _append_context_bundles_section(lines, state, cfg)
    return "\n".join(lines)


def write_lineage_map(
    output_path: str, state: dict[str, Any], cfg: dict[str, Any] | None = None
) -> None:
    path = os.path.normpath(os.path.expandvars(output_path))
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    body = build_lineage_markdown(state, cfg)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(body)
    os.replace(tmp, path)
    logger.debug("Lineage map written: %s", path)


def regenerate_if_enabled(cfg: dict[str, Any], state: dict[str, Any], report_path: str) -> None:
    ls = cfg.get("lineage_settings", {})
    if not bool(ls.get("enabled", True)):
        return
    raw = (ls.get("output_path") or "").strip()
    if raw:
        out = os.path.normpath(os.path.expandvars(raw))
    else:
        out = os.path.join(os.path.dirname(os.path.normpath(report_path)), "DocuDog_lineage.md")
    write_lineage_map(out, state, cfg)
