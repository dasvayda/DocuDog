"""
DocuDog — LiteRT-LM edge performance probe (local MVP).

Measures cold vs warm round-trips and optional classify-style prompt sizes.
Does not start the file watcher.

Usage (from repo root):
  python tools/benchmark_inference.py
  python tools/benchmark_inference.py --config config.json --json-out out/bench.json
"""

from __future__ import annotations

import argparse
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

import psutil  # noqa: E402

from docudog import inference  # noqa: E402


def _rss_mb() -> float:
    return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)


def _log_result(title: str, d: dict) -> None:
    parts = [f"{k}={v}" for k, v in sorted(d.items()) if not k.startswith("_")]
    logging.info("%s %s", title, " ".join(parts))


def main() -> int:
    _add_repo_root()
    from env_litert import apply_litert_env_defaults

    apply_litert_env_defaults()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="LiteRT-LM inference benchmark for DocuDog")
    parser.add_argument(
        "--config",
        default=os.path.join(_REPO, "config.json"),
        help="Path to DocuDog config.json",
    )
    parser.add_argument(
        "--json-out",
        default="",
        help="If set, write full result JSON to this path",
    )
    parser.add_argument(
        "--sweep-chars",
        default="",
        help=(
            "Comma-separated synthetic document sizes for classify-style prompts "
            "(default: 256 + half of max_context_chars + max_context_chars from config)"
        ),
    )
    parser.add_argument(
        "--no-classify-sweep",
        action="store_true",
        help="Only run ping benchmarks, skip classify-style sweeps",
    )
    args = parser.parse_args()

    from main import load_config  # noqa: E402

    cfg = load_config(args.config)
    model_cfg = cfg.get("model", {})
    use_mock = bool(model_cfg.get("use_mock", True))
    bundle_raw = (model_cfg.get("litert_lm_bundle_path") or "").strip()
    bundle = inference._resolve_litert_bundle_path(bundle_raw) if bundle_raw else ""
    max_tokens = int(model_cfg.get("startup_probe_max_tokens", 48))
    max_chars = int(model_cfg.get("max_context_chars", 12000))

    out: dict = {
        "config_path": os.path.abspath(args.config),
        "bundle_resolved": bundle,
        "use_mock": use_mock,
        "max_num_tokens": max_tokens,
        "max_context_chars": max_chars,
        "rss_mb_start": round(_rss_mb(), 2),
    }

    if use_mock or not bundle_raw:
        logging.error("Benchmark needs use_mock=false and a valid litert_lm_bundle_path.")
        if args.json_out:
            os.makedirs(os.path.dirname(os.path.abspath(args.json_out)) or ".", exist_ok=True)
            with open(args.json_out, "w", encoding="utf-8") as f:
                json.dump({**out, "error": "mock or empty bundle"}, f, indent=2)
        return 2

    if not os.path.isfile(bundle):
        logging.error("Bundle is not a file: %s", bundle)
        return 2

    try:
        import litert_lm  # type: ignore  # noqa: F401
    except ImportError as e:
        logging.error("litert_lm not importable: %s", e)
        return 2

    ping = (
        "You are a connectivity test. Reply with exactly one word: OK. No other text."
    )

    rss0 = _rss_mb()
    cold = inference.bench_ping_round_trip(bundle, max_tokens, prompt=ping)
    rss1 = _rss_mb()
    cold["_rss_mb_after"] = round(rss1, 2)
    cold["_rss_delta_mb"] = round(rss1 - rss0, 2)
    out["ping_cold_engine_lifecycle"] = cold
    _log_result("[bench] ping cold (new engine each time)", cold)

    import litert_lm  # type: ignore

    warm: dict = {}
    engine = inference.create_engine(litert_lm, bundle, max_tokens)
    with engine as eng:
        warm["ping_1"] = inference.bench_prompt_on_existing_engine(eng, ping)
        _log_result("[bench] ping warm #1 (reuse engine)", warm["ping_1"])
        warm["ping_2"] = inference.bench_prompt_on_existing_engine(eng, ping)
        _log_result("[bench] ping warm #2 (reuse engine)", warm["ping_2"])
    rss2 = _rss_mb()
    warm["_rss_mb_after"] = round(rss2, 2)
    out["ping_warm_same_engine"] = warm

    if not args.no_classify_sweep:
        if args.sweep_chars.strip():
            sizes = [int(x.strip()) for x in args.sweep_chars.split(",") if x.strip()]
        else:
            sizes = sorted({256, max_chars // 2, max_chars})
        sizes = [min(max(32, s), max_chars) for s in sizes]

        unit = (
            "Edge AI bench. 동일 패턴 텍스트입니다. "
            "보안 문서 분류 로컬 테스트용 더미 본문입니다.\n"
        )
        sweep_rows = []
        for n in sizes:
            reps = (n + len(unit) - 1) // len(unit)
            body = (unit * reps)[:n]
            t_c0 = time.perf_counter()
            parsed = dict(inference.classify_document(body, cfg, should_yield=None))
            inf_src = parsed.pop(inference.DOCUDOG_META_SOURCE, "mock")
            inf_reason = parsed.pop(inference.DOCUDOG_META_REASON, "")
            t_c1 = time.perf_counter()
            tags = parsed.get("tags") or []
            if isinstance(tags, str):
                tags = [tags]
            row = {
                "synthetic_doc_chars": n,
                "classify_wall_seconds": round(t_c1 - t_c0, 6),
                "inference_source": inf_src,
                "inference_reason": inf_reason,
                "classify_json_shape_ok": bool(tags) and bool(parsed.get("security_level")),
                "likely_mock_fallback": inf_src not in inference.REAL_INFERENCE_SOURCES,
                "tags_preview": ",".join(str(t) for t in tags[:5]),
                "security_level": str(parsed.get("security_level", "")),
            }
            sweep_rows.append(row)
            _log_result(f"[bench] classify_document chars={n}", row)
        out["classify_style_sweep"] = sweep_rows

    out["rss_mb_end"] = round(_rss_mb(), 2)
    out["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    if args.json_out:
        path = os.path.abspath(args.json_out)
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        logging.info("Wrote JSON: %s", path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
