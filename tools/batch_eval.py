"""
DocuDog — batch extract + classify over a directory (local MVP / edge QA).

Walks files, applies the same filters as the watcher, extracts text, runs inference.
Writes a CSV report (and optional JSONL) — does not update DocuDog_state.json or classification_report.md.

Usage:
  python tools/batch_eval.py --dir "C:/path/to/samples" --out out/eval.csv
  python tools/batch_eval.py --dir ./samples --limit 20 --extract-only
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time


def _add_repo_root() -> str:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)
    return root


_REPO = _add_repo_root()

from docudog import inference  # noqa: E402
from docudog import router  # noqa: E402


def _iter_files(root: str, recursive: bool) -> list[str]:
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return []
    out: list[str] = []
    if recursive:
        for dirpath, _dirnames, filenames in os.walk(root):
            for name in filenames:
                out.append(os.path.join(dirpath, name))
    else:
        for name in os.listdir(root):
            p = os.path.join(root, name)
            if os.path.isfile(p):
                out.append(p)
    return sorted(out)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Batch extract + classify (DocuDog)")
    parser.add_argument("--dir", required=True, help="Directory of files to evaluate")
    parser.add_argument("--config", default=os.path.join(_REPO, "config.json"))
    parser.add_argument("--out", required=True, help="Output CSV path")
    parser.add_argument("--jsonl", default="", help="Optional JSONL log path (one row per file)")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max files to run through extract/ infer after extension/size filters (0 = no limit)",
    )
    parser.add_argument("--no-recursive", action="store_true", help="Only top-level files in --dir")
    parser.add_argument(
        "--extract-only",
        action="store_true",
        help="Run text extraction only; do not call classify_document",
    )
    args = parser.parse_args()

    from main import load_config  # noqa: E402

    cfg = load_config(args.config)
    eval_root = os.path.abspath(args.dir)
    files = _iter_files(eval_root, recursive=not args.no_recursive)
    rows: list[dict[str, object]] = []

    worked = 0
    for path in files:
        norm = os.path.normpath(os.path.abspath(path))
        rel = os.path.relpath(norm, eval_root) if norm.startswith(eval_root) else os.path.basename(norm)

        if not router.passes_file_filters(cfg, norm):
            rows.append(
                {
                    "path": norm,
                    "rel_path": rel,
                    "status": "filtered_out",
                    "file_size_bytes": "",
                    "extract_ms": "",
                    "extract_chars": "",
                    "skip_or_error": "",
                    "infer_ms": "",
                    "infer_tags": "",
                    "security_level": "",
                    "likely_mock": "",
                    "shape_ok": "",
                }
            )
            continue

        if args.limit and worked >= args.limit:
            break
        worked += 1

        try:
            fsize = os.path.getsize(norm)
        except OSError:
            fsize = -1

        t0 = time.perf_counter()
        text, skip_reason = router.extract_document_text(norm)
        t1 = time.perf_counter()
        extract_ms = round((t1 - t0) * 1000, 3)

        if skip_reason:
            rows.append(
                {
                    "path": norm,
                    "rel_path": rel,
                    "status": "extract_skip",
                    "file_size_bytes": fsize,
                    "extract_ms": extract_ms,
                    "extract_chars": 0,
                    "skip_or_error": skip_reason,
                    "infer_ms": "",
                    "infer_tags": "",
                    "security_level": "",
                    "likely_mock": "",
                    "shape_ok": "",
                }
            )
            continue

        if not (text and text.strip()):
            rows.append(
                {
                    "path": norm,
                    "rel_path": rel,
                    "status": "empty_text",
                    "file_size_bytes": fsize,
                    "extract_ms": extract_ms,
                    "extract_chars": 0,
                    "skip_or_error": "",
                    "infer_ms": "",
                    "infer_tags": "",
                    "security_level": "",
                    "likely_mock": "",
                    "shape_ok": "",
                }
            )
            continue

        if args.extract_only:
            rows.append(
                {
                    "path": norm,
                    "rel_path": rel,
                    "status": "extract_ok",
                    "file_size_bytes": fsize,
                    "extract_ms": extract_ms,
                    "extract_chars": len(text),
                    "skip_or_error": "",
                    "infer_ms": "",
                    "infer_tags": "",
                    "security_level": "",
                    "likely_mock": "",
                    "shape_ok": "",
                }
            )
            continue

        t_i0 = time.perf_counter()
        try:
            parsed = dict(inference.classify_document(text, cfg, should_yield=None))
            inf_src = parsed.pop(inference.DOCUDOG_META_SOURCE, "mock")
            inf_reason = parsed.pop(inference.DOCUDOG_META_REASON, "")
        except Exception as e:
            t_i1 = time.perf_counter()
            rows.append(
                {
                    "path": norm,
                    "rel_path": rel,
                    "status": "infer_error",
                    "file_size_bytes": fsize,
                    "extract_ms": extract_ms,
                    "extract_chars": len(text),
                    "skip_or_error": str(e),
                    "infer_ms": round((t_i1 - t_i0) * 1000, 3),
                    "infer_tags": "",
                    "security_level": "",
                    "inference_source": "",
                    "inference_reason": "",
                    "likely_mock": "",
                    "shape_ok": "false",
                }
            )
            continue
        t_i1 = time.perf_counter()
        infer_ms = round((t_i1 - t_i0) * 1000, 3)
        tags = parsed.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        likely_mock = inf_src not in inference.REAL_INFERENCE_SOURCES
        shape_ok = bool(tags) and bool(parsed.get("security_level"))

        rows.append(
            {
                "path": norm,
                "rel_path": rel,
                "status": "ok",
                "file_size_bytes": fsize,
                "extract_ms": extract_ms,
                "extract_chars": len(text),
                "skip_or_error": "",
                "infer_ms": infer_ms,
                "infer_tags": ";".join(str(t) for t in tags),
                "security_level": str(parsed.get("security_level", "")),
                "inference_source": inf_src,
                "inference_reason": inf_reason,
                "likely_mock": str(likely_mock).lower(),
                "shape_ok": str(shape_ok).lower(),
            }
        )

    fieldnames = [
        "path",
        "rel_path",
        "status",
        "file_size_bytes",
        "extract_ms",
        "extract_chars",
        "skip_or_error",
        "infer_ms",
        "infer_tags",
        "security_level",
        "inference_source",
        "inference_reason",
        "likely_mock",
        "shape_ok",
    ]
    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})

    if args.jsonl:
        jpath = os.path.abspath(args.jsonl)
        os.makedirs(os.path.dirname(jpath) or ".", exist_ok=True)
        with open(jpath, "w", encoding="utf-8") as jf:
            for r in rows:
                jf.write(json.dumps(r, ensure_ascii=False) + "\n")

    n_ok = sum(1 for r in rows if r.get("status") == "ok")
    n_ext_ok = sum(1 for r in rows if r.get("status") == "extract_ok")
    n_skip = sum(1 for r in rows if r.get("status") == "extract_skip")
    n_filt = sum(1 for r in rows if r.get("status") == "filtered_out")
    logging.info(
        "Batch eval done: rows=%s infer_ok=%s extract_ok=%s extract_skip=%s filtered=%s csv=%s",
        len(rows),
        n_ok,
        n_ext_ok,
        n_skip,
        n_filt,
        out_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
