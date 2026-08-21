# DocuDog — 작업·백로그 메모

에이전트와 사람이 **앞으로 할 일**과 **끝낸 일**을 같은 곳에 남기기 위한 문서입니다.  
커밋/PR은 사용자 요청 시에만 포함합니다.

## 사용 방법

- **할 일**: `### 대기 (Next)` 에 bullet 또는 체크박스로 추가.
- **보류**: 모델 단순 비교·주변 도구 실험 등은 `### 보류 (Deferred)` 에만 둡니다.
- **완료**: `### 완료 (Done)` 로 옮기고 한 줄로 **무엇이** 끝났는지 적습니다. 끝에 **YYYY-MM** 또는 **YYYY-MM-DD** 정도로 완료 시점을 달면 이후에 추적하기 좋습니다.

### 항목 ID (`YYMMDD-NN`)

- 형식: **넣은 날** `YYMMDD` + 그날 순번 `NN` (예: `260818-01`).
- ID는 **추적 키**이지 우선순위가 아님. 작은 숫자가 먼저라는 뜻이 아님.
- 우선은 배너·제목의 「우선」또는 본문의 의존 관계로만 표시.
- 같은 날 항목이 늘면 `NN`만 올림. 빠진 번호는 만들지 않음(삭제된 항목은 Done/보류에 남기거나 줄을 지움).
- 예전 `#22` 같은 일련번호는 쓰지 않음. 이미 끝난 일은 Done에 `구 #n` 을 괄호로 남김.

---

### 대기 (Next)

> **2026-08-20 피봇 구현:** `260820-01`~`05` Done. 상세 [`.cursor/plans/pivot-1-260820.md`](.cursor/plans/pivot-1-260820.md).

> **2026-08-18 구현:** `260818-01` 스레드 · `260818-02` file_id. 기획 [`.cursor/plans/threads-file-id.md`](.cursor/plans/threads-file-id.md).

> **2026-08-05 MCP 1차 완료:** `260805-01`. 후속은 `260805-02` · `260818-03`.

> **2026-07-31 구현분은 Done.** ID는 `260731-*` (구 #4~#20). 장문 배경은 git 이력.

**목표(협업·로컬 유용성):** 팀원이 설치했을 때 실사용 체감이 큰 순으로 검증. 아래는 **미완료만**.

- **260818-04. watch settle / min-age (다운로드·Office 잠금)**  
  **출처:** DocBank watched inbox — 크기+mtime 안정 + 선택 최소 파일 나이. 원본은 복사하지 않음.  
  **갭:** 지금은 idle + `file_open_retries`. 파일이 아직 커지는 중(`*.crdownload`, 이어 쓰는 JSONL)은 약함.  
  **방향:** `watch_settings`에 확장자별 settle 초·min age. 분류는 안정된 뒤에만.

- **260818-05. 태그 오버라이드 revision (에이전트 덮어쓰기 방지)**  
  **출처:** DocBank If-Match / stale revision → 412.  
  **방향:** `DocuDog_tag_overrides.json`(및 카테고리 JSON)에 revision. 동기 도구·향후 쓰기 경로가 낡은 스냅샷을 덮지 않음. 원본 문서 파일 trash/GC는 **하지 않음**(state tombstone은 스레드와 별도).

- **260805-02. (후속) MCP Resources · 컨텍스트 팩**  
  도구 호출만이 아니라 `DocuDog_status.md` / `last_classify`를 MCP **resource URI**로 노출; 또는 `docudog_context_pack(topic)`이 검색 Top-K 메타를 **짧은 마크다운 묶음**으로 반환. `260818-03` 증명 필드와 같이. 1차 MCP(`260805-01`)만으로 가치 검증되면 보류 가능.  
  **구 ID:** #21b.

**DocBank 검토 요약 (2026-08-18, 이식하지 않을 것)**  
DocBank = 바이트의 권위(보관소). DocuDog = 의미의 권위(분류·P등급·계보). **스킵:** CAS vault·가상 트리, HTTP 쓰기, 웹/TUI, pack/S3, Go 임베드. Shadow Git/검증 백업은 master-plan 타임머신 에픽에서 **참고만** (`260818-D`).

---

### 보류 (Deferred)

나중에 구현 검토. **모델 A/B 비교·벤치** 용도는 MVP 본류가 아니므로 여기 보관합니다.

- **260818-D. DocBank CAS / 검증 백업 / Shadow Git**  
  분류된 고가치 스냅샷·해시 검증. 폴더 미러·sync-and-share 아님. master-plan Corporate Shadow Git 단계.

- **260604-C. LLM-Wiki 계열 — DocuDog Stage 1과 **제품 목표 불일치****  
  [GeekNews #28208](https://news.hada.io/topic?id=28208)에서 DocuDog watcher·거버넌스와 **다른 레인**. master-plan의 **서버 RAG Graph·벡터 DB** 단계에서 다시 검토할 때 참고만. **구:** 보류 C.

  | 아이디어 | 왜 Stage 1 아님 |
  |----------|-----------------|
  | `DocuDog_index.md` 카탈로그 | `classification_report.md` + `DocuDog_state.json`과 **중복**; “위키 목차”가 아니라 리포트가 이미 산출물 |
  | `tools/query_docs.py` (자연어 Q&A) | **질의형 PKM**; DocuDog은 사용자 질의 없이 **백그라운드 분류**. RAG Graph는 로드맵이지만 서버/그래프 맥락. **외부 에이전트용 읽기 브리지는 `260805-01` MCP**(위키 Q&A 제품 아님) |
  | `DocuDog_entities/*.md` 롤업 | **엔티티 위키**; DocuDog DNA는 **문서 버전 lineage**, Tolkien Gateway식 개념 페이지 아님 |
  | `tools/search_index.py` (BM25) | 로드맵 LanceDB/Chroma와 **같은 축**; watcher MVP 선행 과제 아님 |
  | 일반 full-text / “인기 문서” 피드 | OS 검색과 경쟁; **열람(open) 신호가 없어** 수정 횟수≠중요도. 인기는 shell/ETW 훅 또는 명시적 “핀”이 생긴 뒤 재검토 |

- **260604-A. 하드웨어·모델 가이드 (`whichllm` 연동)**  
  로컬 VRAM에 맞는 후보와 `config` 의 `model.backend` / 번들·LM Studio `model` 선택을 한 화면(또는 `tools/` 스크립트)으로 묶기. **구:** 보류 A.

- **260604-B. 백엔드·모델 비교 배치 러너**  
  동일 코퍼스를 여러 백엔드·모델로 돌려 CSV/JSON으로 태그·등급·시간을 나란히 기록. **구:** 보류 B.

---

### 완료 (Done)

- **260820-01. `.docudog/` 산출물 격리** (`artifact_home`, 기본 `%USERPROFILE%/.docudog/`, 레거시 복사만). — 2026-08-20
- **260820-02. PDF 텍스트 레이어** (`extract_pdf.py`, pypdf; 암호·빈 스캔 skip). — 2026-08-20
- **260820-03. MCP 1클릭 + lineage/bundle + search 날짜** (`--write-all-mcp`, `docudog_get_lineage` / `get_context_bundle`). SSE 보류. — 2026-08-20
- **260820-04. 트레이 + P1 토스트** (`--tray`, `--install-startup`, `notify.py`). status 강제 오픈 없음. — 2026-08-20
- **260820-05. 이종 파일명 한 줄 semantic diff** (`lineage_peer_change_line`, MCP lineage `last_change_summary`). — 2026-08-20
- **260818-03. MCP 에이전트 계약** (`docudog_search` cursor/offset pagination, stable error `code` envelope, invalid input validation). 쓰기 HTTP·루프백 데몬은 안 가져옴. — 2026-08-21
- **260818-01. 문서 스레드** (`docudog/threads.py`, status 「최근 대화」, HTML `<details>`, MCP `docudog_thread`): version + conversation/mixed. 새 MD 파일 없음. — 2026-08-18 · **구 #22**
- **260818-02. 안정 file_id** (`docudog/file_ids.py`): state 레코드 UUID, 동일 SHA+사라진 경로 rename 유지, MCP get `file_id`. — 2026-08-18
- **260813-01. HWP/HWPX 본문 추출** (`docudog/extract_hwp.py`, `syhwp`): hop/rhwp는 `reference/hop` 참조만; watcher가 `.hwp`/`.hwpx`를 분류 파이프에 태움. 암호화·배포용은 스킵. — 2026-08-13
- **260805-01. DocuDog MCP (1차)** (`tools/docudog_mcp.py`, `docudog/mcp_service.py`, [docs/mcp-connect.md](docs/mcp-connect.md), `--write-cursor-mcp` / `--print-install`): 읽기 전용 도구 + Cursor/Claude 연결 DX. — 2026-08-05 · **구 #21**
- **260731-17. 업무 카테고리 few-shot** (`docudog/categories.py`, `DocuDog_categories.example.json`, `category_settings`): 선택지 강제 → `state.category_ids` / 리포트 Tags 접두. — 2026-07-31 · **구 #17**
- **260731-04. 시맨틱 변경 로그** (`docudog/semantic_diff.py`): `summary_history` + `last_change_summary`(휴리스틱; 선택 LLM); status/lineage 섹션. — 2026-07-31 · **구 #4**
- **260731-05. UNC/NAS 감시 보강** (`paths_util`, watcher dedupe/retry, UNC 로그): 공유 잠금 재시도·이벤트 디듑·단일 state 정책 명시. — 2026-07-31 · **구 #5**
- **260731-18. cadence 리마인더** (`docudog/cadence.py`, `cadence_settings`): 주/월 패턴 부재 → status·action digest·`[cadence_miss]` (일 1회). — 2026-07-31 · **구 #18**
- **260731-13. Power-aware idle** (`docudog/power_gate.py`, `idle_settings.min_battery_percent`/`require_charging`): 추론 전 게이트, `[defer_power]`, 큐 유지. — 2026-07-31 · **구 #13**
- **260731-14. 모바일 digest** (`docudog/mobile_digest.py` → `DocuDog_mobile_digest.html`+`.json`). — 2026-07-31 · **구 #14**
- **260731-20b. lineage 경량화** (`include_mermaid` 기본 false, `include_singleton_list`, `slim_intro`). — 2026-07-31 · **구 #20b**
- **260731-12. last_classify companion** (`docudog/last_classify.py` → `DocuDog_last_classify.json`, 분류 성공 시). — 2026-07-31 · **구 #12**
- **260731-11. 액션 다이제스트** (docudog/action_digest.py → status 「지금 할 일」). — 2026-07-31 · **구 #11**
- **260731-08. 거버넌스 lint** (`tools/lint_governance.py` → DocuDog_lint_report.md). — 2026-07-31 · **구 #8**
- **260731-19. 코퍼스 검색 CLI** (`tools/search_corpus.py`). — 2026-07-31 · **구 #19**
- **260731-06. 규칙 힌트 하이브리드** (docudog/rule_hints.py, rule_settings). — 2026-07-31 · **구 #6**
- **260731-16. 유사·맥락 문서 후보** (docudog/related_docs.py, related_paths/last_related). — 2026-07-31 · **구 #16**
- **260731-07. 처리 이벤트 로그** (docudog/activity.py, DocuDog_activity_log.md, paths.activity_log_path): [classify]/[skip_*]/[audit]/[status] append-only. — 2026-07-31 · **구 #7**
- **260731-09. 보안 등급 라벨** (security_level_labels, docudog/security_labels.py): 리포트/audit에 매우 민감 (P1) 형태 + backend 의존 경고 문구. — 2026-07-31 · **구 #9**
- **260731-10. 미분류 사각지대 경고** (docudog/skip_insights.py): 파일명 민감 키워드·state.ops 집계, 리포트 배너 + status 경고. — 2026-07-31 · **구 #10**
- **260731-15. 산출물 에이전트 스펙** ([docs/docudog-output-spec.md](docs/docudog-output-spec.md)): AGENTS.md(개발)와 분리된 산출물 소비 가이드. — 2026-07-31 · **구 #15**
- **260731-20. 현황 대시보드** (docudog/status_dashboard.py, DocuDog_status.md(+html)): lineage=보관 / status=일상 진입점. — 2026-07-31 · **구 #20**
- **260604-01. 워처 없이 단일 파일 분류 스모크** (`tools/classify_one.py`, `docudog/single_file.py`, `python main.py --file PATH`): IDLE·큐 없이 추출→분류→stdout + `classification_report.md` 한 행. — 2026-06-04 · **구 #1**
- **260604-02. 회귀용 최소 문서 픽스처** (`fixtures/` 3종, `fixtures/README.md`, `tools/regression_smoke.py`: 첫 분류 → hash 스킵 → 수정 후 재분류). — 2026-06-04 · **구 #2**(회귀)
- **260604-03. 분류 1회 실행 후 종료 모드** (`python main.py --once`, `DOCUDOG_RUN_ONCE=1`: 큐에서 한 건 처리 후 종료; `skip_idle_wait_for_testing`과 조합 가능). — 2026-06-04 · **구 #3**
- **260519-01. 업무 컨텍스트 묶음 (Context bundles / 시간 윈도우)** (`docudog/context_bundles.py`, watcher 큐 `(경로, 시각)`, `state.context_bundles`, `lineage_settings.context_bundles_*`, `DocuDog_lineage.md` 표). — 2026-05-19 · **구 #2**(번들)
- Stage 1 파이프라인: 감시 + 유휴 + 라우팅 + 텍스트 추출 + 로컬 LLM 분류 + `classification_report.md` + 선택적 `DocuDog_lineage.md` (파일명·해시 기반 pilot). — 2026-05
- 설정: `config.json` + YAML 오버레이 (`docudog/config_loader.py`), `model.backend` — `litert_lm` / `lm_studio` / `openai_compatible`. — 2026-05
- **Audit MVP + LLM** (`docudog/audit.py`): P1/P2 분류 시 `DocuDog_audit_log.md`에 행 추가; `audit_settings`로 켜기/끄기 및 `inference.audit_handling_suggestion` 기반 취급·공유 힌트(JSON). 경로: `paths.audit_log_path` 또는 리포트와 동일 폴더. — 2026-05
- **Lineage + LLM** (`docudog/lineage.py` + `docudog/inference.lineage_cluster_hints_batch`): `lineage_settings.llm_cluster_hints=true` 일 때 다중 파일 그룹별 관계 한 줄(한국어) 힌트 섹션 생성; `llm_max_hint_groups`, `llm_hint_max_tokens` 로 상한. — 2026-05
- **Lineage 유사도·Shadow Git 방향** (`docudog/lineage.py`): `lineage_settings.clustering` = `filename_key` | `similarity` | `both`(기본); 파일명 stem 정규화(`_v1`/`_최종`/`edit` 등) + `difflib.SequenceMatcher` + 요약 **Jaccard**; union-find로 그룹 병합; 파일 수 > `max_files_for_similarity` 이면 fuzzy 생략·로그. Mermaid 정렬은 `last_analyzed_utc` 우선. — 2026-05-19
- **소유자 태그/등급 재지정** (`docudog/owner_tags.py`, `DocuDog_tag_overrides.json`, `tools/sync_tag_overrides.py`): **웹이 아님** — 로컬 JSON; 안내 [docs/owner-tag-overrides.md](docs/owner-tag-overrides.md). 경로: `paths.tag_overrides_path` 또는 state 폴더. 재추론 없이 반영: `python tools/sync_tag_overrides.py` (과거 리포트 행은 미수정). — 2026-05
- **구동 직후 건전성 (경고만)** (`main._log_startup_environment_sanity`): `state_path`·`report_path` 부모 디렉터리 쓰기 프로브, watch 루트 존재, `use_mock` 아니고 HTTP 백엔드일 때 `GET /v1/models` 3s ( `DOCUDOG_SKIP_LM_MODEL_PROBE=1` 이면 스킵). — 2026-05-19
- **마지막 추론 출처** (`docudog/router` + `docudog/reporter`): 성공 분류 후 state 최상위 `last_inference_backend`, `last_inference_utc` 갱신; `classification_report.md` 말미 HTML 주석 블록 + `_Last inference: …_` 한 줄(이전 푸터 치환; `append_note`가 푸터 뒤에 붙은 내용은 보존). — 2026-05-19
