"""Document classification via LiteRT-LM, OpenAI-compatible HTTP servers, or mock."""

from __future__ import annotations

import json
import logging
import glob
import os
import re
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from .config_loader import resolve_http_api_key
from .env_litert import apply_litert_env_defaults, silence_litert_native_stderr

logger = logging.getLogger(__name__)


def _flush_log_handlers() -> None:
    """네이티브 호출 직전/직후 로그가 콘솔에 바로 쓰이도록 flush."""
    for h in logging.root.handlers:
        try:
            h.flush()
        except OSError:
            pass
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except OSError:
        pass


class LiteRTInferenceError(Exception):
    """LiteRT 실패 시 어느 단계에서 터졌는지 보존 (로그 가독성)."""

    def __init__(self, stage: str, cause: BaseException) -> None:
        self.stage = stage
        self.cause = cause
        super().__init__(f"{stage}: {cause}")


class HttpInferenceError(Exception):
    """OpenAI-compatible /chat/completions HTTP 실패 (상태 코드·본문 요약 포함)."""

    def __init__(self, message: str, *, status: int | None = None, body_preview: str = "") -> None:
        self.status = status
        self.body_preview = body_preview
        super().__init__(message)


def _bundle_label(path: str) -> str:
    if not path:
        return ""
    try:
        name = os.path.basename(path)
        if os.path.isfile(path):
            mb = os.path.getsize(path) / (1024 * 1024)
            return f"{name} ({mb:.0f}MB)"
        return name
    except OSError:
        return os.path.basename(path)


def _litert_max_output_tokens(model_cfg: dict[str, Any]) -> int:
    """분류 생성용 상한. 프로브용 startup_probe_max_tokens(짧음)와 혼용하지 않는다."""
    raw = model_cfg.get("litert_max_output_tokens")
    if raw is not None and str(raw).strip() != "":
        return max(32, int(raw))
    return 2048


def _litert_debug_hint() -> str:
    return (
        "DOCUDOG_VERBOSE_INFERENCE=1 (Python traceback); "
        "DOCUDOG_SILENCE_LITERT_STDERR=1 (optional: hide native stderr — can break LiteRT on Windows); "
        "DOCUDOG_LITERT_STREAM=1 (async stream + idle yield, 기본 동기)"
    )


# router / tools에서 pop 할 분류 출처 메타 (리포트/모델 스키마와 무관)
DOCUDOG_META_SOURCE = "_docudog_inference_source"
DOCUDOG_META_REASON = "_docudog_inference_reason"

# 배치 도구 likely_mock 판별용 — 프로덕션 LiteRT / LM Studio / 기타 OpenAI 호환 서버
REAL_INFERENCE_SOURCES = frozenset({"lite_rt", "lm_studio", "openai_compatible"})

_SECURITY_LEVEL_RE = re.compile(r"^P[1-4]$")

SYSTEM_INSTRUCTION = (
    "Classify the document. Output ONLY one JSON object (no markdown, no extra text). "
    'Schema: {"tags":["t1","t2"],"security_level":"P1"|"P2"|"P3"|"P4","summary":"short"}. '
    "2-3 tags; security_level exactly P1, P2, P3, or P4; summary non-empty. "
    "Tags and summary must use the same language as the user input (chat or pasted doc; dominant if mixed)."
)

# OpenAI-compatible servers (LM Studio, Qwen3 reasoning): some models put chain-of-thought in
# reasoning_content and leave content empty — we still parse JSON from visible or reasoning text.
LM_STUDIO_JSON_VISIBLE_INSTRUCTION = (
    "Place the final JSON object in the assistant message content (user-visible). "
    "Do not leave content empty while only filling reasoning/thinking fields."
)

def _assistant_text_from_openai_message(msg: dict[str, Any]) -> str:
    """
    Build assistant text from Chat Completions message object.
    Falls back to reasoning_content / thinking when content is empty (Qwen3, etc.).
    """
    content = msg.get("content")
    if isinstance(content, list):
        pieces: list[str] = []
        for part in content:
            if isinstance(part, dict):
                if part.get("type") == "text":
                    pieces.append(str(part.get("text", "")))
                elif part.get("type") == "reasoning":
                    pieces.append(str(part.get("reasoning", "") or part.get("text", "")))
            elif isinstance(part, str):
                pieces.append(part)
        visible = "".join(pieces)
    elif content is None:
        visible = ""
    else:
        visible = str(content)
    visible = visible.strip()
    if visible:
        return visible

    for key in ("reasoning_content", "reasoning", "thinking"):
        alt = msg.get(key)
        if isinstance(alt, str) and alt.strip():
            logger.info(
                "HTTP chat: empty message.content; using message.%s (%s chars) for parse",
                key,
                len(alt),
            )
            return alt.strip()
    return ""


class YieldToUser(Exception):
    """Raised when inference should stop because the user became active again."""


def mock_inference(_text: str) -> dict[str, Any]:
    """Deterministic JSON-shaped result for tests when no model is available."""
    return {
        "tags": ["mock", "prototype", "docudog"],
        "security_level": "P4",
        "summary": "Mock 분류 결과입니다.\n모델 번들이 없거나 use_mock=true 일 때 사용됩니다.\n실환경에서는 LiteRT-LM 번들 경로를 설정하세요.",
    }


def _with_inference_meta(result: dict[str, Any], source: str, reason: str = "") -> dict[str, Any]:
    out = dict(result)
    out[DOCUDOG_META_SOURCE] = source
    out[DOCUDOG_META_REASON] = reason.strip()
    return out


def _verbose_llm_traceback() -> bool:
    return os.environ.get("DOCUDOG_VERBOSE_INFERENCE", "").strip().lower() in ("1", "true", "yes")


def _validate_and_normalize_classification(d: dict[str, Any]) -> dict[str, Any]:
    """Auto Labeling 스키마: tags, P1-P4, 비어 있지 않은 summary."""
    out = {k: v for k, v in d.items() if not str(k).startswith("_docudog_")}
    tags = out.get("tags")
    if isinstance(tags, str):
        tags = [tags]
    if not isinstance(tags, list):
        raise ValueError("tags must be a list or string")
    norm_tags = [str(t).strip() for t in tags if t is not None and str(t).strip()]
    if not norm_tags:
        raise ValueError("tags empty after normalize")
    out["tags"] = norm_tags
    sec = str(out.get("security_level", "")).strip()
    if not _SECURITY_LEVEL_RE.match(sec):
        raise ValueError(f"security_level must be P1–P4, got {sec!r}")
    out["security_level"] = sec
    summ = str(out.get("summary", "")).strip()
    if not summ:
        raise ValueError("summary must be non-empty")
    out["summary"] = summ
    return out


def _warn_mock_when_lite_expected(reason: str) -> None:
    """use_mock=false 인데 mock 결과로 돌아갈 때만 WARNING (원인 grep 용)."""
    logger.warning("classify_document: MOCK fallback while use_mock=false - %s", reason)


def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model output")
    return json.loads(text[start : end + 1])


def _classification_from_llm_raw(raw_text: str) -> dict[str, Any]:
    return _validate_and_normalize_classification(_extract_json_object(raw_text))


def _build_prompt(document_text: str) -> str:
    # LiteRT-LM 일부 번들은 프리필 상한이 매우 작다(예: 512 토큰). 지시문은 영문 짧게 유지.
    return SYSTEM_INSTRUCTION + "\n\n---\n" + document_text


AUDIT_HANDLING_SYSTEM = (
    "You advise on local document governance. Output ONLY one JSON object (no markdown). "
    'Schema: {"handling_note": "short sentence on storage/sharing/care", '
    '"sharing": "internal_only" | "redact_before_external" | "ok_external"}. '
    "Choose sharing from document sensitivity implied by security_level and excerpt. "
    "handling_note: same language as the excerpt (dominant if mixed)."
)

LINEAGE_HINT_SYSTEM = (
    "You infer relationships between files in lineage groups. Output ONLY one JSON object (no markdown). "
    'Keys are group numbers as strings: "1", "2", ... Values: one short sentence each '
    "hypothesizing the relationship (e.g. copy with different name, estimated revision stage). "
    "Same language as the provided names/snippets (dominant if mixed)."
)


def _validate_audit_handling(d: dict[str, Any]) -> dict[str, str]:
    note = str(d.get("handling_note", "")).strip()
    if not note:
        raise ValueError("handling_note empty")
    share = str(d.get("sharing", "internal_only")).strip()
    allowed = ("internal_only", "redact_before_external", "ok_external")
    if share not in allowed:
        share = "internal_only"
    return {"handling_note": note, "sharing": share}


def _parse_lineage_hints_obj(obj: dict[str, Any]) -> dict[int, str]:
    out: dict[int, str] = {}
    for k, v in obj.items():
        if not isinstance(k, str):
            continue
        key = k.strip()
        if not key.isdigit():
            continue
        idx = int(key)
        s = str(v).strip()
        if s:
            out[idx] = s
    return out


def run_aux_completion(
    system: str,
    user: str,
    config: dict[str, Any],
    max_tokens: int,
    *,
    task_log_label: str,
) -> str:
    """Short JSON-oriented completion for audit/lineage helpers (no mock body)."""
    model_cfg = config.get("model", {})
    if bool(model_cfg.get("use_mock", True)):
        return ""
    mt = max(32, min(512, int(max_tokens)))
    backend = _normalize_backend(model_cfg)
    if backend == BACKEND_DISABLED:
        return ""
    apply_litert_env_defaults()
    try:
        if backend in ("lm_studio", "openai_compatible"):
            lm_cfg = _coerce_lm_studio_section(model_cfg)
            base_url = str(lm_cfg.get("base_url") or "").strip()
            model_name = str(lm_cfg.get("model") or "").strip()
            if not base_url or not model_name:
                return ""
            chat_url = _chat_completions_url(base_url)
            if not chat_url:
                return ""
            tout_raw = lm_cfg.get("timeout_seconds")
            timeout_seconds = (
                float(tout_raw)
                if tout_raw is not None and str(tout_raw).strip() != ""
                else 120.0
            )
            api_key = resolve_http_api_key(lm_cfg)
            temperature = _lm_studio_temperature(lm_cfg)
            messages: list[dict[str, str]] = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            return _openai_http_chat_completion(
                chat_url,
                model=model_name,
                messages=messages,
                timeout_seconds=timeout_seconds,
                api_key=api_key,
                temperature=temperature,
                max_tokens=mt,
            )

        bundle_raw = (model_cfg.get("litert_lm_bundle_path") or "").strip()
        bundle = _resolve_litert_bundle_path(bundle_raw) if bundle_raw else ""
        if not bundle_raw or not os.path.isfile(bundle):
            return ""
        import litert_lm  # type: ignore[import-untyped]

        ulim = int(model_cfg.get("litert_aux_max_user_chars", 200))
        ulim = max(32, ulim)
        if len(user) > ulim:
            logger.debug(
                "LiteRT aux task=%s: clipped user text %s -> %s chars (litert prefill limit)",
                task_log_label,
                len(user),
                ulim,
            )
            user = user[:ulim] + "\n[truncated]"
        prompt = system + "\n\n" + user
        return _litert_generate_raw(litert_lm, bundle, mt, prompt, None)
    except YieldToUser:
        raise
    except Exception as e:
        if _verbose_llm_traceback():
            logger.exception("LLM aux task=%s failed", task_log_label)
        else:
            logger.warning("LLM aux task=%s failed: %s", task_log_label, e)
        return ""


def audit_handling_suggestion(
    document_excerpt: str,
    security_level: str,
    config: dict[str, Any],
) -> dict[str, str] | None:
    audit_cfg = config.get("audit_settings")
    if not isinstance(audit_cfg, dict):
        audit_cfg = {}
    if not bool(audit_cfg.get("llm_handling_hint", True)):
        return None
    max_ex = int(audit_cfg.get("max_excerpt_chars", 1200))
    excerpt = (document_excerpt or "")[: max(0, max_ex)]
    max_tok = int(audit_cfg.get("llm_max_tokens", 256))
    user = f"security_level={security_level}\n---\n{excerpt}"
    raw = run_aux_completion(
        AUDIT_HANDLING_SYSTEM,
        user,
        config,
        max_tok,
        task_log_label="audit_handling",
    )
    if not raw.strip():
        return None
    try:
        obj = _extract_json_object(raw)
        if not isinstance(obj, dict):
            return None
        return _validate_audit_handling(obj)
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.debug("audit_handling parse fail: %s", e)
        return None


def lineage_cluster_hints_batch(
    groups: list[tuple[int, str]],
    config: dict[str, Any],
) -> dict[int, str]:
    """groups: (1-based group index, multiline description)."""
    ls = config.get("lineage_settings")
    if not isinstance(ls, dict):
        ls = {}
    if not bool(ls.get("llm_cluster_hints", False)):
        return {}
    if not groups:
        return {}
    max_tok = int(ls.get("llm_hint_max_tokens", 384))
    blocks: list[str] = []
    for idx, desc in groups:
        blocks.append(f"Group {idx}:\n{desc}")
    user = "\n\n".join(blocks)
    raw = run_aux_completion(
        LINEAGE_HINT_SYSTEM,
        user,
        config,
        max_tok,
        task_log_label="lineage_hints",
    )
    if not raw.strip():
        return {}
    try:
        obj = _extract_json_object(raw)
        if not isinstance(obj, dict):
            return {}
        return _parse_lineage_hints_obj(obj)
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.debug("lineage hints parse fail: %s", e)
        return {}


BACKEND_DISABLED = "none"


def _boolish_config(v: Any) -> bool:
    """Truth value for JSON enable flags."""
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "on")


def _normalize_backend(model_cfg: dict[str, Any]) -> str:
    """
    Resolve active inference backend.

    **Toggle mode:** If `enable_litert_lm` and/or `enable_lm_studio` appears in config,
    booleans choose the backend (avoids typos in `backend` string). If both are true,
    `inference_preference` is `lm_studio` or `litert_lm` (default `lm_studio`).
    If both false, returns ``BACKEND_DISABLED`` (mock with reason).

    **Legacy:** If neither enable key is present, `model.backend` string is used:
    litert_lm | lm_studio | openai_compatible (default litert_lm when empty/unknown).
    """
    toggle_present = (
        "enable_litert_lm" in model_cfg or "enable_lm_studio" in model_cfg
    )
    if toggle_present:
        L = _boolish_config(model_cfg.get("enable_litert_lm", False))
        M = _boolish_config(model_cfg.get("enable_lm_studio", False))
        if L and M:
            pref = str(model_cfg.get("inference_preference") or "lm_studio").strip().lower()
            if pref in ("litert_lm", "litert", "litert-lm", "litertlm"):
                logger.info(
                    "Both backends enabled; inference_preference=%s (litert_lm).",
                    pref,
                )
                return "litert_lm"
            if pref in ("lm_studio", "lmstudio"):
                logger.info(
                    "Both backends enabled; inference_preference=%s (lm_studio).",
                    pref,
                )
                return "lm_studio"
            logger.warning(
                "Both backends on; invalid inference_preference %r — using lm_studio.",
                model_cfg.get("inference_preference"),
            )
            return "lm_studio"
        if M:
            return "lm_studio"
        if L:
            return "litert_lm"
        logger.info(
            "enable_litert_lm and enable_lm_studio both false — inference backends disabled (mock)."
        )
        return BACKEND_DISABLED

    raw = str(model_cfg.get("backend") or "").strip().lower()
    if raw in ("", "litert", "litert_lm", "litert-lm", "litertlm"):
        return "litert_lm"
    if raw in ("lm_studio", "lmstudio"):
        return "lm_studio"
    if raw in ("openai_compatible", "openai"):
        return "openai_compatible"
    logger.warning(
        "classify_document: unknown model.backend %r; using litert_lm",
        raw,
    )
    return "litert_lm"


def resolve_inference_backend(model_cfg: dict[str, Any]) -> str:
    """
    Resolve configured inference backend for diagnostics and startup checks.
    Returns ``litert_lm``, ``lm_studio``, ``openai_compatible``, or ``BACKEND_DISABLED``.
    """
    return _normalize_backend(model_cfg)


def _chat_completions_url(base_url: str) -> str:
    """
    Normalize base URL: strip trailing '/', append /v1/chat/completions
    unless base already ends with /v1.
    """
    b = (base_url or "").strip().rstrip("/")
    if not b:
        return ""
    return f"{b}/chat/completions" if b.endswith("/v1") else f"{b}/v1/chat/completions"


def _openai_models_list_url(base_url: str) -> str:
    b = (base_url or "").strip().rstrip("/")
    if not b:
        return ""
    return f"{b}/models" if b.endswith("/v1") else f"{b}/v1/models"


def probe_openai_compatible_model_ids(
    base_url: str,
    *,
    timeout: float = 5.0,
    api_key: str = "",
) -> tuple[list[str] | None, str]:
    """
    GET /v1/models (OpenAI-compatible). Returns (ids, diagnostic).
    ids is None on HTTP/parse failure. Sends Bearer when api_key is set (required for api.openai.com).
    """
    url = _openai_models_list_url(base_url)
    if not url:
        return None, "empty base_url"
    try:
        req = urllib.request.Request(url, method="GET")
        ak = (api_key or "").strip()
        if ak:
            req.add_header("Authorization", f"Bearer {ak}")
        with urllib.request.urlopen(req, timeout=max(1.0, float(timeout))) as resp:
            raw_body = resp.read().decode("utf-8", errors="replace")
        obj = json.loads(raw_body)
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")[:200]
        except OSError:
            body = ""
        return None, f"HTTP {e.code} {body or e.reason}"
    except urllib.error.URLError as e:
        return None, f"network: {e.reason!r}"
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as e:
        return None, str(e)
    data = obj.get("data") if isinstance(obj, dict) else None
    if not isinstance(data, list):
        return None, "response missing data[]"
    ids: list[str] = []
    for item in data:
        if isinstance(item, dict) and item.get("id"):
            ids.append(str(item["id"]))
    return ids, "ok"


def log_inference_runtime_summary(config: dict[str, Any]) -> None:
    """
    Log which inference path is active and (for HTTP) whether the server lists loaded models.
    Answers: mock vs LiteRT vs LM Studio; configured id vs server /v1/models.
    """
    model_cfg = config.get("model")
    if not isinstance(model_cfg, dict):
        model_cfg = {}
    use_mock = bool(model_cfg.get("use_mock", True))
    if use_mock:
        logger.info(
            "Inference: use_mock=true — LiteRT and HTTP classify are skipped."
        )
        return
    backend = _normalize_backend(model_cfg)
    if backend == BACKEND_DISABLED:
        logger.info(
            "Inference: enable_litert_lm and enable_lm_studio both false — classify uses mock."
        )
        return

    if backend in ("lm_studio", "openai_compatible"):
        lm_cfg = _coerce_lm_studio_section(model_cfg)
        base = str(lm_cfg.get("base_url") or "").strip()
        mid = str(lm_cfg.get("model") or "").strip()
        logger.info(
            "Inference: backend=%s | url=%s | config model id=%s",
            backend,
            base or "(missing)",
            mid or "(missing — HTTP classify will use mock until set)",
        )
        skip_probe = os.environ.get("DOCUDOG_SKIP_LM_MODEL_PROBE", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        if skip_probe:
            logger.info("Inference: skipping GET /v1/models (DOCUDOG_SKIP_LM_MODEL_PROBE=1).")
            return
        if not base:
            return
        tout = lm_cfg.get("timeout_seconds")
        probe_timeout = (
            min(12.0, float(tout))
            if tout is not None and str(tout).strip() != ""
            else 5.0
        )
        ids, diag = probe_openai_compatible_model_ids(
            base,
            timeout=probe_timeout,
            api_key=resolve_http_api_key(lm_cfg),
        )
        if ids is None:
            logger.warning(
                "Inference: GET /v1/models failed (%s). "
                "LM Studio local server off, wrong IP/port, or not OpenAI-compatible endpoint.",
                diag,
            )
            return
        if not ids:
            logger.warning(
                "Inference: server returned zero models — load a model in LM Studio and keep the server running."
            )
            return
        logger.info(
            "Inference: server lists %s model id(s); e.g. %s%s",
            len(ids),
            ", ".join(ids[:5]),
            " ..." if len(ids) > 5 else "",
        )
        if mid:
            if mid in ids:
                logger.info("Inference: config model id is on the server list (match).")
            else:
                logger.warning(
                    "Inference: config model id %r is NOT in the server's list — "
                    "requests may fail or the server may substitute another model. "
                    "Use one of the ids from the log above.",
                    mid,
                )
        return

    raw = (model_cfg.get("litert_lm_bundle_path") or "").strip()
    bundle = _resolve_litert_bundle_path(raw) if raw else ""
    short = os.path.basename(bundle) if bundle else "(no path)"
    ok = bool(bundle and os.path.isfile(bundle))
    logger.info(
        "Inference: backend=litert_lm | bundle=%s | file_ok=%s",
        short,
        ok,
    )
    cap = model_cfg.get("litert_classify_context_cap")
    mc = int(model_cfg.get("max_context_chars", 12000))
    if cap is None or str(cap).strip() == "":
        if mc > 400:
            logger.warning(
                "Inference: many Gemma/LiteRT bundles cap prefill around 256 tokens. "
                "If classify fails with Input token ids are too long, set "
                "model.litert_classify_context_cap (try 200–400) and keep "
                "model.litert_aux_max_user_chars small for P1/P2 audit hints."
            )
    else:
        logger.info(
            "Inference: litert_classify_context_cap=%s (max_context_chars=%s)",
            cap,
            mc,
        )


def _coerce_lm_studio_section(model_cfg: dict[str, Any]) -> dict[str, Any]:
    raw = model_cfg.get("lm_studio")
    return dict(raw) if isinstance(raw, dict) else {}


def _lm_studio_temperature(lm_cfg: dict[str, Any]) -> float | None:
    raw = lm_cfg.get("temperature", None)
    if raw is None or str(raw).strip() == "":
        return None
    return float(raw)


def _lm_studio_classify_max_tokens(model_cfg: dict[str, Any], lm_cfg: dict[str, Any]) -> int:
    raw = lm_cfg.get("max_tokens")
    if raw is not None and str(raw).strip() != "":
        return max(16, int(raw))
    return _litert_max_output_tokens(model_cfg)


def _openai_http_chat_completion(
    url: str,
    *,
    model: str,
    messages: list[dict[str, str]],
    timeout_seconds: float,
    api_key: str = "",
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """POST chat/completions JSON; Bearer if api_key. Returns assistant text."""
    payload: dict[str, Any] = {"model": model, "messages": messages}
    if max_tokens is not None:
        payload["max_tokens"] = int(max_tokens)
    if temperature is not None:
        payload["temperature"] = temperature
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=encoded, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    ak = (api_key or "").strip()
    if ak:
        req.add_header("Authorization", f"Bearer {ak}")
    to = float(timeout_seconds) if timeout_seconds and timeout_seconds > 0 else 120.0
    try:
        with urllib.request.urlopen(req, timeout=to) as resp:
            raw_body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except OSError:
            err_body = ""
        prev = err_body.strip().replace("\n", " ")
        if len(prev) > 400:
            prev = prev[:397] + "..."
        raise HttpInferenceError(
            f"HTTP {e.code}: {prev or e.reason}",
            status=e.code,
            body_preview=prev,
        ) from e
    except urllib.error.URLError as e:
        es = str(e).lower()
        tnote = (
            f" (read timeout was {to:g}s; try larger model.lm_studio.timeout_seconds)"
            if "timed out" in es or "time out" in es
            else ""
        )
        raise HttpInferenceError(f"network error: {e}{tnote}") from e
    except OSError as e:
        es = str(e).lower()
        tnote = (
            f" (read timeout was {to:g}s; try larger model.lm_studio.timeout_seconds)"
            if "timed out" in es
            else ""
        )
        raise HttpInferenceError(f"io error: {e}{tnote}") from e
    try:
        obj = json.loads(raw_body)
    except json.JSONDecodeError as e:
        snippet = raw_body.strip().replace("\n", " ")
        if len(snippet) > 240:
            snippet = snippet[:237] + "..."
        raise HttpInferenceError(f"invalid JSON response: {e}; body={snippet!r}") from e
    try:
        choices = obj["choices"]
        msg0 = choices[0]["message"]
        if not isinstance(msg0, dict):
            raise HttpInferenceError(f"choices[0].message not object: {type(msg0).__name__}")
    except (KeyError, IndexError, TypeError) as e:
        raise HttpInferenceError(f"missing choices[0].message: {e!r}") from e
    return _assistant_text_from_openai_message(msg0)


def _open_engine(
    litert_lm: Any, bundle: str, max_num_tokens: int | None = None
) -> Any:
    """최후 수단 생성자 폴백. 가능하면 max_num_tokens를 유지한다."""
    with silence_litert_native_stderr():
        if max_num_tokens is not None:
            try:
                return litert_lm.Engine(
                    bundle, litert_lm.Backend.CPU(), max_num_tokens=max_num_tokens
                )
            except TypeError:
                try:
                    return litert_lm.Engine(bundle, max_num_tokens=max_num_tokens)
                except TypeError:
                    pass
        try:
            return litert_lm.Engine(bundle, litert_lm.Backend.CPU())
        except Exception:
            return litert_lm.Engine(bundle)


def create_engine(
    litert_lm: Any,
    bundle: str,
    max_num_tokens: int,
) -> Any:
    """
    Create a LiteRT-LM engine with the same constructor fallbacks as startup_model_probe.

    Used by benchmark tools; callers own the context manager lifecycle.
    """
    with silence_litert_native_stderr():
        try:
            return litert_lm.Engine(bundle, max_num_tokens=max_num_tokens)
        except TypeError:
            try:
                return litert_lm.Engine(
                    bundle, litert_lm.Backend.CPU(), max_num_tokens=max_num_tokens
                )
            except TypeError:
                return _open_engine(litert_lm, bundle, max_num_tokens)


def bench_ping_round_trip(
    bundle: str,
    max_num_tokens: int,
    prompt: str | None = None,
) -> dict[str, Any]:
    """
    One engine lifecycle: open engine, one conversation, one sync message.

    Returns timing fields (seconds, perf_counter) and reply metadata for benchmarks.
    """
    apply_litert_env_defaults()
    import litert_lm  # type: ignore[import-untyped]

    ping = prompt or (
        "You are a connectivity test. Reply with exactly one word: OK. No other text."
    )
    t0 = time.perf_counter()
    with silence_litert_native_stderr():
        engine = create_engine(litert_lm, bundle, max_num_tokens)
        t_eng = time.perf_counter()
        with engine as eng:
            t_ctx0 = time.perf_counter()
            with eng.create_conversation() as conv:
                t_conv = time.perf_counter()
                raw = _sync_message(conv, ping)
                t_done = time.perf_counter()
    return {
        "seconds_engine_construct": t_eng - t0,
        "seconds_enter_engine_ctx": t_ctx0 - t_eng,
        "seconds_create_conversation": t_conv - t_ctx0,
        "seconds_inference": t_done - t_conv,
        "seconds_total": t_done - t0,
        "reply_chars": len(raw or ""),
        "reply_preview": (raw or "").strip().replace("\n", " ")[:120],
    }


def bench_prompt_on_existing_engine(
    engine_ctx: Any,
    prompt: str,
) -> dict[str, Any]:
    """Second conversation on an already-open engine (warm timing)."""
    t0 = time.perf_counter()
    with silence_litert_native_stderr():
        with engine_ctx.create_conversation() as conv:
            t1 = time.perf_counter()
            raw = _sync_message(conv, prompt)
            t2 = time.perf_counter()
    return {
        "seconds_create_conversation": t1 - t0,
        "seconds_inference": t2 - t1,
        "seconds_total": t2 - t0,
        "reply_chars": len(raw or ""),
        "reply_preview": (raw or "").strip().replace("\n", " ")[:160],
    }


def _sync_message(conversation: Any, prompt: str) -> str:
    msg = conversation.send_message(prompt)
    raw = ""
    for item in msg.get("content", []):
        if item.get("type") == "text":
            raw += item.get("text", "")
    return raw


def _stream_message(
    conversation: Any,
    prompt: str,
    should_yield: Optional[Callable[[], bool]],
) -> str:
    accumulated: list[str] = []
    stream = conversation.send_message_async(prompt)
    for chunk in stream:
        if should_yield and should_yield():
            raise YieldToUser()
        for item in chunk.get("content", []):
            if item.get("type") == "text":
                accumulated.append(item.get("text", ""))
    return "".join(accumulated)


def _litert_generate_raw(
    litert_lm: Any,
    bundle: str,
    max_gen_tokens: int,
    prompt: str,
    should_yield: Optional[Callable[[], bool]],
) -> str:
    """
    LiteRT 한 사이클(엔진 -> 대화 -> send). 실패 시 stage 를 남긴다 (원인 추적용).

    기본은 동기 send_message — Windows 등에서 send_message_async(XNNPACK)가
    "Failed to allocate tensors" 로 실패하는 사례가 있음.
    스트리밍(유휴 중간 양보): DOCUDOG_LITERT_STREAM=1
    """
    stage = "create_engine"
    try:
        with silence_litert_native_stderr():
            engine = create_engine(litert_lm, bundle, max_gen_tokens)
            stage = "engine_session"
            with engine as eng:
                stage = "create_conversation"
                with eng.create_conversation() as conv:
                    stage = "generate"
                    stream = os.environ.get(
                        "DOCUDOG_LITERT_STREAM", "0"
                    ).strip().lower() in ("1", "true", "yes")
                    if stream:
                        try:
                            return _stream_message(conv, prompt, should_yield)
                        except AttributeError:
                            pass
                    if should_yield and should_yield():
                        raise YieldToUser()
                    return _sync_message(conv, prompt)
    except YieldToUser:
        raise
    except Exception as e:
        raise LiteRTInferenceError(stage, e) from e


def _log_text_preview(text: str, max_len: int = 200) -> str:
    s = (text or "").strip().replace("\r", " ").replace("\n", " ")
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s


def _startup_engine_max_tokens(model_cfg: dict[str, Any], *, dialogue: bool) -> int:
    """
    Engine(..., max_num_tokens=) 값.

    일부 LiteRT-LM 빌드는 이 값을 '프리필+생성' 공통 상한으로 쓰므로,
    채팅 템플릿이 붙는 startup_dialogue 에는 작은 값(예: 48)을 쓰면
    send_message 직후 네이티브 abort 로 프로세스가 조용히 죽을 수 있다.
    """
    if dialogue:
        raw = model_cfg.get("startup_dialogue_max_tokens")
        if raw is not None and str(raw).strip() != "":
            return max(128, int(raw))
        return 512
    return int(model_cfg.get("startup_probe_max_tokens", 48))


def _default_startup_dialogue_turns() -> list[str]:
    """LiteRT-LM 문서 샘플과 유사한 짧은 영문 2턴 (프리필 토큰 부담 최소화)."""
    return [
        "What is the capital of France?",
        "Name one famous landmark there. Reply in one short phrase.",
    ]


def _coerce_startup_dialogue_turns(model_cfg: dict[str, Any]) -> list[str]:
    raw = model_cfg.get("startup_dialogue_turns")
    if isinstance(raw, list):
        out = [str(x).strip() for x in raw if str(x).strip()]
        if len(out) >= 2:
            return out
    return _default_startup_dialogue_turns()


def _run_startup_dialogue_probe(
    litert_lm: Any,
    bundle: str,
    max_gen_tokens: int,
    user_turns: list[str],
) -> None:
    """
    한 번의 Engine + Conversation 안에서 사용자 메시지를 연속 전송(짧은 대화 테스트).
    도구 호출은 litert-lm CLI preset 과 달리 Python API에서 자동화하지 않음.
    """
    stage = "create_engine"
    try:
        with silence_litert_native_stderr():
            engine = create_engine(litert_lm, bundle, max_gen_tokens)
            stage = "engine_session"
            with engine as eng:
                stage = "create_conversation"
                with eng.create_conversation() as conv:
                    for t_idx, user_msg in enumerate(user_turns):
                        stage = f"dialogue_turn_{t_idx + 1}"
                        logger.info(
                            "LLM startup dialogue: turn %s/%s user_chars=%s user_preview=%r",
                            t_idx + 1,
                            len(user_turns),
                            len(user_msg),
                            _log_text_preview(user_msg, 220),
                        )
                        _flush_log_handlers()
                        logger.info(
                            "LLM startup dialogue: turn %s/%s awaiting assistant (send_message)...",
                            t_idx + 1,
                            len(user_turns),
                        )
                        _flush_log_handlers()
                        try:
                            raw = _sync_message(conv, user_msg)
                        except KeyboardInterrupt:
                            logger.warning(
                                "LLM startup dialogue interrupted during turn %s/%s (KeyboardInterrupt).",
                                t_idx + 1,
                                len(user_turns),
                            )
                            _flush_log_handlers()
                            raise
                        logger.info(
                            "LLM startup dialogue: turn %s/%s assistant_chars=%s assistant_preview=%r",
                            t_idx + 1,
                            len(user_turns),
                            len(raw or ""),
                            _log_text_preview(raw or "", 320),
                        )
                        _flush_log_handlers()
    except Exception as e:
        raise LiteRTInferenceError(stage, e) from e


def _startup_model_probe_http(backend: str, model_cfg: dict[str, Any]) -> None:
    lm_cfg = _coerce_lm_studio_section(model_cfg)
    base_url = str(lm_cfg.get("base_url") or "").strip()
    model_name = str(lm_cfg.get("model") or "").strip()
    if not base_url or not model_name:
        logger.warning(
            "LLM probe: skipped | backend=%s | empty base_url or lm_studio.model",
            backend,
        )
        return
    url = _chat_completions_url(base_url)
    if not url:
        logger.warning("LLM probe: skipped | backend=%s | invalid base_url", backend)
        return
    tout_raw = lm_cfg.get("timeout_seconds")
    timeout_seconds = (
        float(tout_raw)
        if tout_raw is not None and str(tout_raw).strip() != ""
        else 120.0
    )
    api_key = resolve_http_api_key(lm_cfg)
    ping_msgs = [{"role": "user", "content": "Reply with exactly one word: OK. No other text."}]
    ping_max_tokens = max(16, min(32, int(model_cfg.get("startup_probe_max_tokens", 48))))

    try:
        raw_reply = _openai_http_chat_completion(
            url,
            model=model_name,
            messages=ping_msgs,
            timeout_seconds=timeout_seconds,
            api_key=api_key,
            temperature=None,
            max_tokens=ping_max_tokens,
        )
        snippet = (raw_reply or "").strip().replace("\n", " ")
        if len(snippet) > 120:
            snippet = snippet[:117] + "..."
        logger.info(
            "LLM probe: ok | backend=%s | model=%s | url=%s | reply_chars=%s | reply=%r",
            backend,
            model_name,
            url,
            len(raw_reply or ""),
            snippet or "(empty)",
        )
    except HttpInferenceError as e:
        if _verbose_llm_traceback():
            logger.exception(
                "LLM startup test: failed backend=%s (classify may fall back to mock)",
                backend,
            )
        else:
            logger.error(
                "LLM startup test: failed backend=%s | %s",
                backend,
                e,
            )


def _resolve_litert_bundle_path(raw: str) -> str:
    """Expand env vars; if a directory, pick the first *.litertlm inside."""
    path = os.path.normpath(os.path.expandvars((raw or "").strip()))
    if not path:
        return ""
    if os.path.isfile(path):
        return path
    if os.path.isdir(path):
        candidates = sorted(glob.glob(os.path.join(path, "**", "*.litertlm"), recursive=True))
        if not candidates:
            candidates = sorted(glob.glob(os.path.join(path, "*.litertlm")))
        return candidates[0] if candidates else path
    return path


def startup_model_probe(config: dict[str, Any]) -> None:
    """
    구동 시 추론 백엔드 연결 확인.

    LiteRT backend: 번들 로드 또는 짧은 대화/단일 ping.
    lm_studio / openai_compatible: HTTP chat/completions 짧은 ping(LiteRT 번들 없음).

    DOCUDOG_SKIP_MODEL_PROBE=1 로 끔. startup_probe 기본 false. 강제: DOCUDOG_FORCE_STARTUP_PROBE=1.
    """
    if os.environ.get("DOCUDOG_SKIP_MODEL_PROBE", "").strip().lower() in ("1", "true", "yes"):
        logger.info("LLM probe: skipped (DOCUDOG_SKIP_MODEL_PROBE=1).")
        return

    model_cfg = config.get("model", {})
    force_probe = os.environ.get("DOCUDOG_FORCE_STARTUP_PROBE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )
    if not bool(model_cfg.get("startup_probe", False)) and not force_probe:
        logger.info(
            "LLM probe: skipped (model.startup_probe=false or omitted; bundle loads on first classify). "
            "Force: DOCUDOG_FORCE_STARTUP_PROBE=1."
        )
        return

    use_mock = bool(model_cfg.get("use_mock", True))
    backend = _normalize_backend(model_cfg)

    if use_mock:
        logger.info(
            "LLM: mode=mock - 추론을 건너뜁니다 (use_mock=true)."
        )
        return

    if backend == BACKEND_DISABLED:
        logger.info("LLM probe: skipped (enable_litert_lm and enable_lm_studio both false).")
        return

    if backend in ("lm_studio", "openai_compatible"):
        _startup_model_probe_http(backend, model_cfg)
        return

    bundle_raw = (model_cfg.get("litert_lm_bundle_path") or "").strip()

    if not bundle_raw:
        logger.warning(
            "LLM: use_mock=false 인데 litert_lm_bundle_path 가 비었습니다 - 분류는 mock 결과를 씁니다."
        )
        return

    bundle = _resolve_litert_bundle_path(bundle_raw)

    if os.path.isdir(bundle):
        logger.error(
            "LLM: 번들 디렉터리에 .litertlm 파일이 없습니다 - %s",
            bundle,
        )
        return

    if not os.path.isfile(bundle):
        logger.error(
            "LLM: 번들 파일이 없습니다 - %s (설정값 %s)",
            bundle,
            bundle_raw,
        )
        return

    apply_litert_env_defaults()
    logger.warning(
        "LLM startup_probe: loading .litertlm into RAM (typically several GB). "
        "If Cursor or the OS freezes, set model.startup_probe=false and use an external terminal."
    )
    try:
        import litert_lm  # type: ignore[import-untyped]
    except ImportError as e:
        logger.error("LLM: litert_lm import 실패 (%s) - mock 로 분류합니다.", e)
        return

    ping = (
        "You are a connectivity test. Reply with exactly one word: OK. "
        "No other text."
    )
    use_dialogue = bool(model_cfg.get("startup_dialogue_probe", True))

    try:
        if use_dialogue:
            max_tokens = _startup_engine_max_tokens(model_cfg, dialogue=True)
            turns = _coerce_startup_dialogue_turns(model_cfg)
            logger.info(
                "LLM startup dialogue: session start | turns=%s engine_max_num_tokens=%s bundle=%s",
                len(turns),
                max_tokens,
                _bundle_label(bundle),
            )
            _run_startup_dialogue_probe(litert_lm, bundle, max_tokens, turns)
            logger.info(
                "LLM startup dialogue: complete | lite_rt ok | turns=%s bundle=%s",
                len(turns),
                _bundle_label(bundle),
            )
        else:
            max_tokens = _startup_engine_max_tokens(model_cfg, dialogue=False)
            raw = _litert_generate_raw(litert_lm, bundle, max_tokens, ping, None)
            snippet = (raw or "").strip().replace("\n", " ")
            if len(snippet) > 120:
                snippet = snippet[:117] + "..."
            logger.info(
                "LLM probe: ok | lite_rt | bundle=%s | max_gen_tokens=%s | reply_chars=%s | reply=%r",
                _bundle_label(bundle),
                max_tokens,
                len(raw or ""),
                snippet or "(empty)",
            )
    except LiteRTInferenceError as e:
        if _verbose_llm_traceback():
            logger.exception(
                "LLM startup test: lite_rt failed stage=%s - classify may fall back to mock",
                e.stage,
            )
        else:
            logger.error(
                "LLM startup test: lite_rt failed | stage=%s | %s | %s",
                e.stage,
                e.cause,
                _litert_debug_hint(),
            )
        return


def _classify_document_openai_http(
    clipped: str,
    model_cfg: dict[str, Any],
    source_tag: str,
    should_yield: Optional[Callable[[], bool]],
) -> dict[str, Any]:
    lm_cfg = _coerce_lm_studio_section(model_cfg)
    base_url = str(lm_cfg.get("base_url") or "").strip()
    model_name = str(lm_cfg.get("model") or "").strip()
    if not base_url or not model_name:
        _warn_mock_when_lite_expected("lm_studio base_url/model empty (skipped HTTP classify)")
        return _with_inference_meta(
            mock_inference(clipped), "mock", "http_config_incomplete"
        )

    chat_url = _chat_completions_url(base_url)
    if not chat_url:
        _warn_mock_when_lite_expected("lm_studio base_url invalid")
        return _with_inference_meta(mock_inference(clipped), "mock", "bad_base_url")

    tout_raw = lm_cfg.get("timeout_seconds")
    timeout_seconds = (
        float(tout_raw)
        if tout_raw is not None and str(tout_raw).strip() != ""
        else 120.0
    )
    api_key = resolve_http_api_key(lm_cfg)
    temperature = _lm_studio_temperature(lm_cfg)
    max_tokens = _lm_studio_classify_max_tokens(model_cfg, lm_cfg)

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": SYSTEM_INSTRUCTION + " " + LM_STUDIO_JSON_VISIBLE_INSTRUCTION,
        },
        {"role": "user", "content": clipped},
    ]

    try:
        if should_yield and should_yield():
            raise YieldToUser()
        raw_text = _openai_http_chat_completion(
            chat_url,
            model=model_name,
            messages=messages,
            timeout_seconds=timeout_seconds,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except YieldToUser:
        raise
    except HttpInferenceError as e:
        if _verbose_llm_traceback():
            logger.exception(
                "LLM task=classify status=fail source=%s",
                source_tag,
            )
        else:
            logger.error(
                "LLM task=classify status=fail source=%s | %s | "
                "If timed out: raise model.lm_studio.timeout_seconds (remote/slow host); "
                "optionally lower model.litert_max_output_tokens or lm_studio.max_tokens.",
                source_tag,
                e,
            )
        _warn_mock_when_lite_expected(str(e))
        return _with_inference_meta(mock_inference(clipped), "mock", "http_error")

    try:
        validated = _classification_from_llm_raw(raw_text)
        tags = validated.get("tags")
        tstr = tags if isinstance(tags, list) else [tags] if tags else []
        logger.info(
            "LLM task=classify status=ok source=%s tags=%s security=%s",
            source_tag,
            tstr[:5],
            validated.get("security_level"),
        )
        return _with_inference_meta(validated, source_tag, "")
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(
            "LLM task=classify status=bad_json retry=1 source=%s detail=%s | %s",
            source_tag,
            e,
            _litert_debug_hint(),
        )
        retry_user = (
            clipped
            + "\n\nOutput valid JSON only. security_level: P1, P2, P3, or P4 only."
        )
        retry_messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": SYSTEM_INSTRUCTION + " " + LM_STUDIO_JSON_VISIBLE_INSTRUCTION,
            },
            {"role": "user", "content": retry_user},
        ]
        try:
            if should_yield and should_yield():
                raise YieldToUser()
            raw2 = _openai_http_chat_completion(
                chat_url,
                model=model_name,
                messages=retry_messages,
                timeout_seconds=timeout_seconds,
                api_key=api_key,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            validated2 = _classification_from_llm_raw(raw2)
            tags2 = validated2.get("tags")
            t2 = tags2 if isinstance(tags2, list) else [tags2] if tags2 else []
            logger.info(
                "LLM task=classify status=ok source=%s retry=1 tags=%s security=%s",
                source_tag,
                t2[:5],
                validated2.get("security_level"),
            )
            return _with_inference_meta(
                validated2, source_tag, "retry_after_schema_fail"
            )
        except YieldToUser:
            raise
        except HttpInferenceError as e:
            logger.warning(
                "LLM task=classify status=fail retry=1 source=%s | %s",
                source_tag,
                e,
            )
        except (json.JSONDecodeError, ValueError) as e2:
            logger.warning(
                "LLM task=classify status=fail retry=1 bad_json source=%s | %s",
                source_tag,
                e2,
            )
        except Exception as e:
            logger.warning(
                "LLM task=classify status=fail retry=1 source=%s | %s",
                source_tag,
                e,
            )

    _warn_mock_when_lite_expected("JSON/schema parse or retry failed")
    return _with_inference_meta(mock_inference(clipped), "mock", "json_or_schema_failed")


def classify_document(
    document_text: str,
    config: dict[str, Any],
    should_yield: Optional[Callable[[], bool]] = None,
) -> dict[str, Any]:
    """
    Classify document text into tags / security_level / summary.

    should_yield: if provided and returns True, streaming inference stops and
    raises YieldToUser (cooperative yield when the user is active again).

    반환 dict에 DOCUDOG_META_* 키가 포함될 수 있음 — router에서 제거할 것.
    """
    apply_litert_env_defaults()
    model_cfg = config.get("model", {})
    use_mock = bool(model_cfg.get("use_mock", True))
    backend = _normalize_backend(model_cfg)
    max_chars = int(model_cfg.get("max_context_chars", 12000))
    if not use_mock and backend == "litert_lm":
        cap_raw = model_cfg.get("litert_classify_context_cap")
        if cap_raw is not None and str(cap_raw).strip() != "":
            max_chars = min(max_chars, max(64, int(cap_raw)))
    clipped = document_text[:max_chars]

    if use_mock:
        logger.debug("Using mock inference (use_mock=true)")
        return _with_inference_meta(mock_inference(clipped), "mock", "use_mock=true")

    if backend == BACKEND_DISABLED:
        logger.debug("Using mock inference (inference backends disabled via enable_* flags)")
        return _with_inference_meta(
            mock_inference(clipped), "mock", "inference_backends_disabled"
        )

    if backend in ("lm_studio", "openai_compatible"):
        return _classify_document_openai_http(
            clipped, model_cfg, backend, should_yield
        )

    bundle_raw = (model_cfg.get("litert_lm_bundle_path") or "").strip()
    bundle = _resolve_litert_bundle_path(bundle_raw) if bundle_raw else ""

    if not bundle_raw:
        logger.debug("Using mock inference (bundle path empty)")
        _warn_mock_when_lite_expected("litert_lm_bundle_path is empty")
        return _with_inference_meta(mock_inference(clipped), "mock", "no_bundle_path")

    if not os.path.isfile(bundle):
        _warn_mock_when_lite_expected(f"bundle is not a file: {bundle!r}")
        return _with_inference_meta(mock_inference(clipped), "mock", "bundle_not_file")

    try:
        import litert_lm  # type: ignore[import-untyped]
    except ImportError as e:
        _warn_mock_when_lite_expected(f"litert_lm import failed: {e}")
        return _with_inference_meta(mock_inference(clipped), "mock", "import_error")

    prompt = _build_prompt(clipped)
    max_gen = _litert_max_output_tokens(model_cfg)

    try:
        raw_text = _litert_generate_raw(
            litert_lm, bundle, max_gen, prompt, should_yield
        )
    except YieldToUser:
        raise
    except LiteRTInferenceError as e:
        if _verbose_llm_traceback():
            logger.exception(
                "LLM task=classify status=fail source=lite_rt stage=%s",
                e.stage,
            )
        else:
            logger.error(
                "LLM task=classify status=fail source=lite_rt stage=%s cause=%s | %s",
                e.stage,
                e.cause,
                _litert_debug_hint(),
            )
        _warn_mock_when_lite_expected(f"{e.stage}: {type(e.cause).__name__}: {e.cause}")
        return _with_inference_meta(mock_inference(clipped), "mock", "engine_error")

    try:
        validated = _classification_from_llm_raw(raw_text)
        tags = validated.get("tags")
        tstr = tags if isinstance(tags, list) else [tags] if tags else []
        logger.info(
            "LLM task=classify status=ok source=lite_rt tags=%s security=%s",
            tstr[:5],
            validated.get("security_level"),
        )
        return _with_inference_meta(validated, "lite_rt", "")
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning(
            "LLM task=classify status=bad_json retry=1 detail=%s | %s",
            e,
            _litert_debug_hint(),
        )
        retry_prompt = (
            _build_prompt(clipped)
            + "\n\nOutput valid JSON only. security_level: P1, P2, P3, or P4 only."
        )
        try:
            raw2 = _litert_generate_raw(
                litert_lm, bundle, max_gen, retry_prompt, None
            )
            validated2 = _classification_from_llm_raw(raw2)
            tags2 = validated2.get("tags")
            t2 = tags2 if isinstance(tags2, list) else [tags2] if tags2 else []
            logger.info(
                "LLM task=classify status=ok source=lite_rt retry=1 tags=%s security=%s",
                t2[:5],
                validated2.get("security_level"),
            )
            return _with_inference_meta(validated2, "lite_rt", "retry_after_schema_fail")
        except LiteRTInferenceError as e:
            logger.warning(
                "LLM task=classify status=fail retry=1 lite_rt stage=%s | %s | %s",
                e.stage,
                e.cause,
                _litert_debug_hint(),
            )
        except (json.JSONDecodeError, ValueError) as e2:
            logger.warning(
                "LLM task=classify status=fail retry=1 bad_json | %s | %s",
                e2,
                _litert_debug_hint(),
            )
        except Exception as e:
            logger.warning(
                "LLM task=classify status=fail retry=1 | %s | %s",
                e,
                _litert_debug_hint(),
            )
        _warn_mock_when_lite_expected("JSON/schema parse or retry failed")
        return _with_inference_meta(mock_inference(clipped), "mock", "json_or_schema_failed")
