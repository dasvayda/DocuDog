"""
LiteRT-LM 분류 한계 진단 (수동 절차 1~4 자동화).

config.json 의 번들을 그대로 쓰고, classify_document 만 여러 설정으로 호출한다.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import sys
import time
from pathlib import Path

# repo root
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

os.chdir(_ROOT)

from docudog import inference  # noqa: E402
from docudog import router  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stdout,
)


def _load_base_config() -> dict:
    with open(_ROOT / "config.json", encoding="utf-8") as f:
        return json.load(f)


def _one_classify(doc: str, base: dict, **model_kw: object) -> tuple[bool, str, str]:
    cfg = copy.deepcopy(base)
    m = cfg.setdefault("model", {})
    for k, v in model_kw.items():
        m[k] = v
    t0 = time.perf_counter()
    try:
        out = inference.classify_document(doc, cfg)
    except Exception as e:
        return False, f"exception:{type(e).__name__}:{e}", ""
    dt = time.perf_counter() - t0
    src = str(out.get(inference.DOCUDOG_META_SOURCE, ""))
    reason = str(out.get(inference.DOCUDOG_META_REASON, ""))
    ok = src == "lite_rt"
    tag = f"{dt:.1f}s source={src} reason={reason!r}"
    return ok, tag, reason


def _long_corpus(target_chars: int) -> str:
    """의미 없는 반복으로 길이만 맞춤 (실제 문서 길이/토큰 스윕용)."""
    unit = "한 줄의 샘플 문서 텍스트입니다. 샘플 문서 분류 테스트. " * 10
    out: list[str] = []
    n = 0
    while n < target_chars:
        out.append(unit)
        n += len(unit)
    return "".join(out)[:target_chars]


def _pick_pptx() -> Path | None:
    downloads = Path(os.path.expandvars("%USERPROFILE%")) / "Downloads"
    if not downloads.is_dir():
        return None
    candidates = sorted(downloads.glob("*.pptx"))
    for p in candidates:
        if "260427" in p.name or "업데이트" in p.name:
            return p
    return candidates[0] if candidates else None


def main() -> None:
    print("=== DocuDog LiteRT classify diagnostics ===", flush=True)
    base = _load_base_config()
    m = base.get("model", {})
    if m.get("use_mock", True):
        print("config model.use_mock is true — set false for lite_rt tests.", flush=True)
        sys.exit(2)
    bundle = m.get("litert_lm_bundle_path", "")
    if not bundle or not Path(os.path.expandvars(str(bundle))).is_file():
        print("Bundle missing — check litert_lm_bundle_path", flush=True)
        sys.exit(2)

    # 진단: Python 측 상세 + 네이티브 stderr(기본이 fd 리다이렉트 안 함)
    os.environ["DOCUDOG_VERBOSE_INFERENCE"] = "1"

    short_txt = (
        "이 문서는 짧은 테스트입니다. "
        "내용: 프로젝트 킥오프 회의록. 내부용.\n"
        "참석: 팀 A, 팀 B."
    )

    results: list[tuple[str, bool, str]] = []

    def record(name: str, ok: bool, detail: str) -> None:
        results.append((name, ok, detail))
        status = "OK " if ok else "FAIL"
        print(f"[{status}] {name} | {detail}", flush=True)

    # --- 4번: 짧은 텍스트 vs PPT 추출 ---
    print("\n--- D4: short .txt-like vs real PPT extract ---", flush=True)
    ok, det, _ = _one_classify(short_txt, base)
    record("short_text (default max_context / max_out)", ok, det)

    ppt_path = _pick_pptx()
    ppt_text, skip = (None, None)
    if ppt_path:
        ppt_text, skip = router.extract_document_text(str(ppt_path))
        if skip or not (ppt_text and ppt_text.strip()):
            record("pptx extract", False, skip or "empty text")
        else:
            print(
                f"PPTX: {ppt_path.name} extracted_chars={len(ppt_text)}",
                flush=True,
            )
            ok, det, _ = _one_classify(ppt_text, base)
            record("pptx_full_text (default limits)", ok, det)
    else:
        print("No .pptx in Downloads — skip PPT branch.", flush=True)

    # --- 2~3번: 긴 코퍼스 + max_context_chars / litert_max_output_tokens ---
    print("\n--- D2+D3: long corpus sweeps (stderr visible) ---", flush=True)
    corpus_20k = _long_corpus(20_000)

    combos: list[tuple[int, int]] = [
        (12_000, 2048),
        (12_000, 512),
        (12_000, 256),
        (8000, 2048),
        (4000, 2048),
        (2000, 2048),
        (2000, 512),
    ]
    for ctx, max_out in combos:
        name = (
            f"long_corpus max_context_chars={ctx} litert_max_output_tokens={max_out}"
        )
        ok, det, _ = _one_classify(
            corpus_20k,
            base,
            max_context_chars=ctx,
            litert_max_output_tokens=max_out,
        )
        record(name, ok, det)
        if ok:
            print(
                f"  -> first passing long-text combo: context={ctx} max_out={max_out}",
                flush=True,
            )
            break

    print("\n=== summary ===", flush=True)
    for name, ok, det in results:
        print(f"{'PASS' if ok else 'FAIL'}\t{name}\t{det}", flush=True)


if __name__ == "__main__":
    main()
