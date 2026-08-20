# AGENTS.md

Concise guidance for AI coding agents working on **DocuDog** (see product intent in [master-plan.md](master-plan.md)).

## Product snapshot

- **Goal**: Background file watching + idle-aware scheduling, local document text extraction, **on-device LLM** classification (tags, P1–P4 security level, summary), append-only Markdown report and optional lineage output.
- **MVP scope**: "Watcher" pipeline only: no UI, no server sync in code paths that ship today.
- **User-facing feature map:** [Features.md](Features.md) (what to open, what you get). Module inventory: [docs/implemented-features.md](docs/implemented-features.md).

## Repository map (Python)

| Area | Module | Role |
|------|--------|------|
| Entry | `main.py` (repo root) | Config/state, single-instance lock, idle loop, orchestration; imports **`docudog`** |
| Watch | `docudog/watcher.py` | Windows idle (`GetLastInputInfo`), watchdog queues |
| Route | `docudog/router.py` | Filters, hash dedupe, extract, call `inference`, reporter |
| HWP | `docudog/extract_hwp.py` | `.hwp`/`.hwpx` text via **`syhwp`**; `reference/hop` is the desktop/rhwp format reference only |
| LLM | `docudog/inference.py` | LiteRT-LM, LM Studio/OpenAI-compatible HTTP (`/v1/chat/completions`), mock |
| LiteRT env | `docudog/env_litert.py` | Native log suppression, `apply_litert_env_defaults()` |
| Report | `docudog/reporter.py` | Append rows to `classification_report.md` and sync sibling `classification_report.html` |
| Lineage | `docudog/lineage.py` | Mermaid map + optional `llm_cluster_hints`; **similarity** clustering (`clustering`, Jaccard+difflib) |
| Threads | `docudog/threads.py`, `docudog/file_ids.py` | Status inbox threads + stable `file_id` (rename-safe) |
| Audit | `docudog/audit.py` | P1/P2 append-only `DocuDog_audit_log.md` + optional LLM handling hint |
| Owner tags | `docudog/owner_tags.py`, `DocuDog_tag_overrides.json`, `tools/sync_tag_overrides.py` | **No web UI** — local JSON; guide [docs/owner-tag-overrides.md](docs/owner-tag-overrides.md) |
| Categories | `docudog/categories.py`, `DocuDog_categories.json` | Owner taxonomy + few-shot prompt (`category_settings`) |
| Semantic log | `docudog/semantic_diff.py` | `summary_history` / optional LLM one-line change |
| Paths/UNC | `docudog/paths_util.py` | UNC-safe normalize, file open retries |
| MCP | `tools/docudog_mcp.py`, `docudog/mcp_service.py` | Read-only corpus tools for Cursor/Claude; [docs/mcp-connect.md](docs/mcp-connect.md) |
| Activity | `docudog/activity.py` | Append-only `DocuDog_activity_log.md` |
| Status | `docudog/status_dashboard.py` | Short `DocuDog_status.md` (+html); lineage stays archive |
| Output spec (readers) | [docs/docudog-output-spec.md](docs/docudog-output-spec.md) | How agents/scripts consume local artifacts (not this repo's `AGENTS.md`) |
| Config | `docudog/config_loader.py`, `main.load_config()`, `config.json` | Defaults + YAML overlay (`config.yml` / `config.yaml`): watch roots, filters, paths, `model.*`, `audit_settings`, `lineage_settings` |

**Paths in config:** prefer forward slashes (`%USERPROFILE%/Documents/...`) so values paste cleanly from Explorer; Windows accepts them and `os.path.normpath` / `paths_util.normalize_fs_path` normalizes. UNC roots (`\\server\share\...`) are supported for watch; sharing locks retry via `watch_settings.file_open_retries`. `state_path` / `report_path` (and set `audit_log_path`) parent folders are created at startup if missing. Watch roots (`target_directories`) are **not** auto-created. Single state/report instance — concurrent NAS writers are serialized by the daemon queue.

## Conventions

- Prefer **small, focused diffs**; match existing style (type hints, `logger` not `print` for runtime).
- **No emoji** in user-facing string output (logging, CLI messages).
- Do **not** commit secrets (`.env`, tokens). Commits/PRs only when the user asks.
- Plan-only Markdown under `.cursor/plans/` when the user requests a plan file.
- **Task backlog / done log**: use [to-do-list.md](to-do-list.md) to record MVP-aligned upcoming work, deferred items, and completed items so sessions stay aligned with [master-plan.md](master-plan.md).
- **Implemented feature inventory (human/AI review)**: keep [docs/implemented-features.md](docs/implemented-features.md) updated when shipping behavior changes.
- **Owner tag overrides** (not a web app): [docs/owner-tag-overrides.md](docs/owner-tag-overrides.md).

## Model backends (toggle preferred)

- **Toggles (recommended):** If `enable_litert_lm` and/or `enable_lm_studio` exists under `model`, booleans pick the backend (no `litert_lm` / `lm_studio` spelling mistakes).
  - Only **`enable_lm_studio`: true** → HTTP (`model.lm_studio`).
  - Only **`enable_litert_lm`: true** → LiteRT (`litert_lm_bundle_path`).
  - **Both true** → **`inference_preference`**: `lm_studio` or `litert_lm` (default `lm_studio`).
  - **Both false** → inference off → mock (`inference_backends_disabled`), unless `use_mock` already short-circuits.
- **Legacy:** If **neither** enable key is present, **`model.backend`** string: `litert_lm` | `lm_studio` | `openai_compatible` (same as before).

HTTP / LM Studio block:

- **`lm_studio`**: `base_url`, `model` (server id), `timeout_seconds` (default 120), optional `api_key`, `temperature`, optional `max_tokens`. Empty `model` skips HTTP → mock.

- **OpenAI cloud (dev):** omit `enable_*` toggles; set `model.backend: openai_compatible`, `lm_studio.base_url: https://api.openai.com/v1`, `lm_studio.model: gpt-4o-mini` (or another small model). Secrets: repo-root **`.env`** with `OPENAI_API_KEY=...` (gitignored; loaded by `config_loader`). Empty `api_key` falls back to `OPENAI_API_KEY` / `DOCUDOG_API_KEY`. Template: [`.env.example`](.env.example).

- **`startup_probe`**: for HTTP backends, short `/v1/chat/completions` ping; same `DOCUDOG_SKIP_MODEL_PROBE` / `DOCUDOG_FORCE_STARTUP_PROBE` as LiteRT. `GET /v1/models` sends Bearer when a key is present (needed for api.openai.com).

- Overlay: merged via `deep_merge`; put only deltas in YAML — see [`config.example.yml`](config.example.yml).

## LLM / LiteRT (`model.backend`: `litert_lm`)

- **구동 경로 건전성**: `main.py`가 시작 시 state/report 부모 폴더 쓰기·watch 경로·(HTTP 백엔드 시) `GET /v1/models` 를 **경고만** 기록합니다.
- **마지막 추론 메타**: 분류 성공 시 `DocuDog_state.json` 최상위 `last_inference_backend`, `last_inference_utc`; 리포트 하단 `_Last inference: …_`(치환).

- Real inference (local LiteRT-LM path): **`litert_lm`** Python package + **`*.litertlm`** bundle path (`model.litert_lm_bundle_path`).
- On startup: **`startup_probe`** defaults to **false** (omit or false) so **main does not load the multi-GB .litertlm immediately** (avoids freezing Cursor/IDE when RAM is tight). First real classify loads the bundle. Set **`startup_probe`: true** or **`DOCUDOG_FORCE_STARTUP_PROBE=1`** only when you explicitly want a startup connectivity test.
- When startup probe runs on **`litert_lm`**: **`startup_dialogue_probe`** runs a **2-turn** chat unless false; use **`startup_dialogue_max_tokens`** (default **512**) — not **`startup_probe_max_tokens`** (48) for dialogue. **`startup_dialogue_turns`**: optional JSON array (≥2 strings).
- Mock path: `model.use_mock: true`; or LiteRT path when bundle missing/invalid; or HTTP backends when `lm_studio`/`model` is incomplete — results carry `_docudog_inference_source` / `_docudog_inference_reason` until router pops them for the report.
- **`litert_max_output_tokens`**: caps **generation** length; some **`.litertlm`** builds still enforce a much smaller **prefill** limit (system + user combined). Errors like `Input token ids are too long ... 579 >= 256` mean prefill exceeded — lower **`litert_classify_context_cap`** (classification text budget) and/or **`litert_aux_max_user_chars`** (audit/P1–P2 hints, lineage aux). **`max_context_chars`** can stay higher for extraction/reporting; LiteRT classify uses the cap when set.

  - `DOCUDOG_VERBOSE_INFERENCE=1` — Python tracebacks for inference failures
  - `DOCUDOG_SKIP_LM_MODEL_PROBE=1` — do not call `GET /v1/models` at startup (HTTP backend summary)
  - `DOCUDOG_SILENCE_LITERT_STDERR=1` — **optional**: redirect native LiteRT stderr to NUL during engine calls (default is **off** so stderr stays attached; turning this on can break LiteRT on Windows)
  - `DOCUDOG_DEBUG=1` — more Python `DEBUG` logs from orchestrator/watcher (same effect as `runtime_settings.debug_python_logs: true` in `config.json`; use the config flag when running `main.py` from the IDE without env vars)

## What agents should not assume

- Cloning **Google LiteRT** C++ source is **not** required for normal DocuDog use (see [ARCHITECTURE.md](ARCHITECTURE.md)).

## Future (master-plan, not necessarily implemented)

Shadow Git, vector DB, server graph/RAG, filter drivers, LoRA — treat as roadmap unless code exists.
