# 구현 기능 목록 (Implemented features)

DocuDog **현재 코드베이스에 존재하는 동작**을 사람·AI 리뷰용으로 정리한 문서입니다.  
[ARCHITECTURE.md](../ARCHITECTURE.md)는 구조와 데이터 흐름에 초점을 두고, 본 문서는 **기능 단위 인벤토리**에 초점을 둡니다. 장기 비전은 [master-plan.md](../master-plan.md)를 참고하세요(플랜 전부가 구현된 것은 아님).

---

## 문서 유지

| 항목 | 권장 |
|------|------|
| **갱신 시점** | 관측 가능한 동작이 바뀌는 PR·릴리스마다 (새 모듈, 새 설정 키, 산출물 형식 변경 등) |
| **갱신하지 않아도 되는 경우** | 리팩터링으로 공개 동작이 동일한 경우(필요 시 한 줄만) |

**문서 이력**

| 날짜 | 요약 |
|------|------|
| 2026-05-19 | 초안 작성(Stage 1 기능 정리); 코어 모듈을 **`docudog/`** 패키지로 정리(`main.py`는 루트 유지) |
| 2026-05-19 | Context bundles(시간 윈도우 공동 출현): `lineage_settings` 키, `state.context_bundles`, lineage Markdown 섹션 |
| 2026-06-04 | 단일 파일 스모크(`classify_one`, `main --file`), `--once`/`DOCUDOG_RUN_ONCE`, `fixtures/` + `regression_smoke.py` |
| 2026-07-22 | 분류 리포트 HTML 동기화(`classification_report.html`, MD와 동일 basename) |
| 2026-07-31 | activity log · 등급 라벨 · 미분류 경고 · `DocuDog_status` · `docs/docudog-output-spec.md` |
| 2026-07-31 | #11 액션 다이제스트 · #8 lint_governance · #19 search_corpus · #6 rule_hints · #16 related_docs |
| 2026-07-31 | #18 cadence · #13 power gate · #14 mobile digest · #20b lineage slim · #12 last_classify |
| 2026-07-31 | #17 categories · #4 semantic_history · #5 UNC/retry |

---

## 범위

- **포함**: 이 저장소의 Python MVP(Stage 1 Watcher) — 백그라운드 감시, 유휴 스케줄링, 추출·분류, 로컬 Markdown/JSON 산출.
- **레이아웃**: 실행 진입점은 저장소 루트의 **`main.py`**; 그 외 코어 모듈은 **`docudog/`** 패키지(`docudog/inference.py` 등).
- **제외**: `reference/whichllm` 등 **참조용 서브트리**의 기능은 본 목록에 넣지 않음(해당 README·문서 따름).

---

## 1. 오케스트레이션

| 기능 | 설명 | 모듈/위치 |
|------|------|-----------|
| 설정 로드 | `config.json` + 동일 디렉터리의 `config.yml` / `config.yaml` 딥 머지 | `docudog/config_loader.py`, `main.load_config` |
| 시작 시 건전성(경고만) | `state_path`·`report_path` 부모 디렉터리 쓰기 프로브, watch 루트 존재, HTTP 백엔드 시 `GET /v1/models`(짧은 타임아웃); `DOCUDOG_SKIP_LM_MODEL_PROBE=1` 시 스킵 | `main._log_startup_environment_sanity` |
| 단일 인스턴스 | PID·`main.py` 경로 기반 run lock; 동일 스크립트의 이전 프로세스 종료 시도 | `main._ensure_single_instance_or_replace` |
| 백그라운드 우선순위 | Windows에서 `IDLE_PRIORITY_CLASS` 등 | `main.apply_background_priority` |
| 추론 런타임 요약 로그 | 백엔드·번들/URL·모델 ID 등 | `docudog/inference.log_inference_runtime_summary` |
| 시작 시 모델 프로브 | 설정에 따라 LiteRT 또는 HTTP 짧은 호출 | `docudog/inference.startup_model_probe` |
| 유휴 루프 | 사용자 입력 유휴 후 큐 처리; 설정·환경변수로 유휴 시간 조정 | `main.py`, `docudog/watcher.sleep_while_busy` 등 |
| 전력 게이트 | `idle_settings.min_battery_percent` / `require_charging` — 추론 직전 defer, activity `[defer_power]` | `docudog/power_gate.py`, `docudog/router` |
| 주기 문서 cadence | `cadence_settings.rules` — 주/월 부재 감지 → status·digest·`[cadence_miss]` | `docudog/cadence.py` |
| 단일 파일·1회 종료 | `main.py --file`, `--once`, `DOCUDOG_RUN_ONCE=1`; `tools/classify_one.py` | `docudog/single_file.py`, `main.py` |

---

## 2. 파일 감시·큐

| 기능 | 설명 | 모듈 |
|------|------|------|
| 디렉터리 감시 | `watchdog` 기반, 설정 루트·제외 디렉터리 | `docudog/watcher.py` |
| 큐 페이로드 | `(절대 경로, 이벤트 Unix 시각)`; 선택 `on_seen` 콜백으로 링 버퍼 등 부가 기록 | `docudog/watcher.py` |
| 기존 파일 시드 | 시작 시 조건 맞는 파일 큐 적재 | `docudog/watcher.seed_queue_from_existing_files` |
| Windows 유휴 | `GetLastInputInfo` 기반 초 단위 유휴(비-Windows는 경고 후 0초로 가정) | `docudog/watcher.seconds_since_last_input` |

---

## 3. 라우팅·텍스트 추출

| 기능 | 설명 | 모듈 |
|------|------|------|
| 확장자·크기 필터 | `file_filters` | `docudog/router.passes_file_filters` |
| 추출 지원 형식 | `.txt`, `.md`, `.docx`, `.pptx`, `.xlsx` | `docudog/router.extract_document_text` |
| MVP 스킵 | `.pdf`, `.hwp`, `.hwpx` 등 — 추출 없이 스킵 사유 기록 | `docudog/router` |
| 중복·재분류 방지 | 파일 전체 SHA-256; 동일 해시면 LLM 생략·`last_checked_utc` 갱신 | `docudog/router.process_file` |
| 소유자 오버라이드 | `DocuDog_tag_overrides.json`로 태그·`security_level` 우선 | `docudog/owner_tags.py` |

---

## 4. LLM 분류·보조 추론

| 기능 | 설명 | 모듈 |
|------|------|------|
| 백엔드 선택 | `enable_litert_lm` / `enable_lm_studio` 토글 및 `inference_preference`; 레거시 `model.backend` 문자열 | `docudog/inference._normalize_backend` |
| 분류 출력 | JSON: `tags`, `security_level`(형식만 `P1`–`P4` 검증), `summary`; 선택 `rule_settings` 힌트·등급 floor | `docudog/inference.classify_document`, `docudog/rule_hints` |
| LiteRT 프리필 완화 | `litert_classify_context_cap`, `litert_aux_max_user_chars` 등 | `docudog/inference` |
| HTTP 백엔드 | OpenAI 호환 `POST /v1/chat/completions`; LM Studio 등 | `docudog/inference._openai_http_chat_completion` |
| Mock | `use_mock`, 번들/URL 미설정, 백엔드 비활성 등 | `docudog/inference.mock_inference` 등 |
| P1/P2 감사 보조 힌트 | 짧은 JSON — 저장·공유 수준 제안(`audit_handling_suggestion`) | `docudog/inference.audit_handling_suggestion` |
| Lineage LLM 힌트 | 다중 파일 그룹 관계 한 줄 요약(옵션) | `docudog/inference.lineage_cluster_hints_batch`, `docudog/lineage.py` |
| Lineage 유사도 그룹 | `clustering`=`both` 등: stem 정규화 + difflib + summary Jaccard, union-find | `docudog/lineage._build_multi_groups` |
| Context bundles | 분류 직후 앵커 파일의 FS 이벤트 시각 ±N분·같은 폴더(또는 `context_bundle_extra_directories`) 내 다른 경로를 `state.context_bundles`에 누적; `DocuDog_lineage.md` 표(옵션) | `docudog/context_bundles.py`, `docudog/router.process_file`, `docudog/lineage._append_context_bundles_section` |
| 업무 카테고리 | `DocuDog_categories.json` + `category_settings` — 프롬프트 선택지, `state.category_ids` | `docudog/categories.py` |
| 시맨틱 변경 | hash 변경 시 `summary_history` / `last_change_summary` (선택 LLM) | `docudog/semantic_diff.py` |
| UNC/NAS | 경로 정규화, 이벤트 디듑, 파일 열기 재시도 | `docudog/paths_util.py`, `docudog/watcher.py` |

---

## 5. 산출물·저장소

| 산출물 | 설명 | 모듈 |
|--------|------|------|
| `classification_report.md` | 분류 행 append; Inference 열(구 리포트 호환); 말미 `_Last inference: ..._` 메타(HTML 주석 블록으로 치환) | `docudog/reporter.py` |
| `classification_report.html` | MD와 **동일 basename**; 분류/노트 append 및 시작 시 MD에서 동기화(브라우저 열람용) | `docudog/reporter.sync_report_html` |
| `DocuDog_activity_log.md` | 운영 타임라인 append (`[classify]`/`[skip_*]`/`[audit]` 등) | `docudog/activity.py` |
| `DocuDog_status.md` (+html) | 현황 대시보드(짧게): 액션 다이제스트·오늘 분류·P1/P2·미분류 경고·등급/backend 분포·최신본 Top·유사 후보 | `docudog/status_dashboard.py`, `action_digest.py` |
| 규칙 힌트 하이브리드 | `rule_settings` 키워드/정규식 → 프롬프트 힌트 + 등급 floor (`rule_floor`) | `docudog/rule_hints.py`, `router` |
| 유사·맥락 후보 | 분류 후 `related_paths` / `last_related` (lineage key·요약 Jaccard·context bundle) | `docudog/related_docs.py` |
| `DocuDog_state.json` | 파일별 해시·메타; 최상위 `last_inference_backend`, `last_inference_utc`; 선택 `context_bundles`; `ops` 스킵 집계 | `main.load_state` / `docudog/router` |
| `DocuDog_audit_log.md` | **P1·P2**일 때만 append; 선택적 handling 힌트 열 | `docudog/audit.py` |
| `DocuDog_lineage.md` | 옵션; 파일명·해시 기반 lineage; Mermaid는 `include_mermaid`(기본 off); 선택 **Context bundles** | `docudog/lineage.py` |
| `DocuDog_mobile_digest.html`(+`.json`) | status 축소판 (오늘/P1·P2/액션/cadence) | `docudog/mobile_digest.py` |
| `DocuDog_last_classify.json` | 최근 분류 1건 (Share companion) | `docudog/last_classify.py` |
| 스킵/메모 | `reporter.append_note` — 리포트에 인용 블록 형태 메모 | `docudog/reporter.py` |

---

## 6. 도구 스크립트 (`tools/`)

| 스크립트 | 역할 |
|-----------|------|
| `download_litert_gemma.py` | 기본 HF 기준 LiteRT Gemma 번들 다운로드 안내 |
| `classify_one.py` | 워처·유휴 없이 **한 파일** 추출→분류→stdout + 리포트 (`docudog/single_file.py`) |
| `regression_smoke.py` | `fixtures/` 복사본으로 분류→hash 스킵→수정→재분류 (mock) |
| `sync_tag_overrides.py` | 오버라이드 JSON을 state에 재반영(재추론 없음) |
| `batch_eval.py`, `benchmark_inference.py`, `quick_test.py` | 평가·벤치·스모크 — 저장소 루트를 `sys.path`에 넣고 `from docudog import ...` |
| `lint_governance.py` | state/audit 경량 린트 → `DocuDog_lint_report.md` (원본 파일 미수정) |
| `search_corpus.py` | state 메타 검색 CLI (`--level`/`--tag`/`--query`) |

---

## 7. 명시적 비구현·한계 (리뷰 시 참고)

다음은 **현 코드에서 기대하면 안 되는 것**에 가깝습니다.

- **보안 등급 P1–P4의 조직 정책 매핑** 또는 키워드·규칙 기반 자동 배정
- **웹 UI** 또는 중앙 서버로의 자동 동기화(마스터 플랜의 서버 RAG·DLP **미구현**)
- **PDF/HWP 본문 추출** (MVP 스킵)
- **커널·이메일 후킹** 수준의 실시간 DLP 차단

---

## 관련 링크

- [ARCHITECTURE.md](../ARCHITECTURE.md) — 컴포넌트·데이터 흐름·LiteRT 참고
- [AGENTS.md](../AGENTS.md) — 에이전트용 요약·규칙
- [docs/owner-tag-overrides.md](owner-tag-overrides.md) — 태그·등급 수동 재지정
