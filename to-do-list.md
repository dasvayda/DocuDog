# DocuDog — 작업·백로그 메모

에이전트와 사람이 **앞으로 할 일**과 **끝낸 일**을 같은 곳에 남기기 위한 문서입니다.  
커밋/PR은 사용자 요청 시에만 포함합니다.

## 사용 방법

- **할 일**: `### 대기 (Next)` 에 bullet 또는 체크박스로 추가.
- **보류**: 모델 단순 비교·주변 도구 실험 등은 `### 보류 (Deferred)` 에만 둡니다.
- **완료**: `### 완료 (Done)` 로 옮기고 한 줄로 **무엇이** 끝났는지 적습니다. 끝에 **YYYY-MM** 또는 **YYYY-MM-DD** 정도로 완료 시점을 달면 이후에 추적하기 좋습니다.

---

### 대기 (Next)

**목표(협업·로컬 유용성 검증):** 팀원이 설치했을 때 실사용 체감이 큰 순으로 검증한다. 아래 항목이 그에 맞춘 제안·백로그다.

- **4. 시맨틱 변경 로그 (Semantic Commit Log / LLM diff 요약)**  
  **레퍼런스:** Git의 `word-diff`·lineage graph는 **줄·단어 단위 raw diff**에 익숙한 개발 워크플로용. 사무·기획 문서는 동일하게 보여주면 오히려 읽기 부담.  
  **아이디어:** 동일 논리 문서의 **이전 SHA vs 새 SHA**에서 추출한 텍스트 **델타(바뀐 구간)**만 로컬 LLM에 짧게 넘겨 **한 줄 요약**을 생성.  
  **구현(방향):** `lineage.py`(또는 `router` 메타 갱신 시점)에서 “같은 lineage 그룹·연속 버전” 후보를 잡고, 두 스냅샷 본문 차이를 제한 길이로 만든 뒤 프롬프트 예: `이 두 문서 조각의 차이를 한 문장으로 요약.` → 결과를 state 또는 lineage 전용 필드에 누적.  
  **산출:** `DocuDog_lineage.md`에 개발자용 patch 나열 대신 **사람 언어 버전 로그**(예: “v1.0 대비 v1.1: 예산 표 숫자·일정 월 변경”) 형태로 섹션 추가. 토큰·프리필 한도는 기존 `litert_aux_max_user_chars` 등과 정렬.  
  **주의:** 대용량 문서는 델타 샘플링·청크 요약 전략 필요.

- **5. 공유 폴더·NAS(UNC) 감시·확장 검증**  
  **왜:** 노트북 단독을 넘어 `\\NAS\…` 또는 마운트된 네트워크 드라이브를 `watch_settings.target_directories`에 넣었을 때 팀 자료가 같이 정리되는지 검증.  
  **방향:** Windows **UNC·네트워크 경로**에서 `watchdog` 관찰이 안정적인지 재현·보완; **다중 사용자·동시 저장** 시 큐/상태가 꼬이지 않도록 **잠금·재시도·단일 리포트/단일 state** 정책 명확화(필요 시 파일 잠금 또는 큐 직렬화).

- **6. 규칙 엔진 + LLM 하이브리드(P1~P4·Audit 신뢰도)**  
  **왜:** 등급을 LLM에만 맡기면 “왜 P1?”·“왜 스킵?” 같은 내부 테스트 시 신뢰 이슈가 난다.  
  **방향:** `config.json`(또는 YAML)에 **정규식·키워드 리스트**(사내 프로젝트 코드, 고객명, 주민번호 패턴 등)를 두고, `router`/`inference`에서 **1차 매칭** 후 분류 프롬프트에 **힌트·가이드**(예: 민감 키워드 포함 시 상위 등급 후보)를 주는 하이브리드. 룰 적분·설명 로그(리포트 또는 state 메타)까지 범위 정하기.

---

### 보류 (Deferred)

나중에 구현 검토. **모델 A/B 비교·벤치** 용도는 MVP 본류가 아니므로 여기 보관합니다.

- **A. 하드웨어·모델 가이드 (`whichllm` 연동)**  
  로컬 VRAM에 맞는 후보와 `config` 의 `model.backend` / 번들·LM Studio `model` 선택을 한 화면(또는 `tools/` 스크립트)으로 묶기.

- **B. 백엔드·모델 비교 배치 러너**  
  동일 코퍼스를 여러 백엔드·모델로 돌려 CSV/JSON으로 태그·등급·시간을 나란히 기록.


---

### 완료 (Done)

- **1. 워처 없이 단일 파일 분류 스모크** (`tools/classify_one.py`, `docudog/single_file.py`, `python main.py --file PATH`): IDLE·큐 없이 추출→분류→stdout + `classification_report.md` 한 행. — 2026-06-04
- **2. 회귀용 최소 문서 픽스처** (`fixtures/` 3종, `fixtures/README.md`, `tools/regression_smoke.py`: 첫 분류 → hash 스킵 → 수정 후 재분류). — 2026-06-04
- **3. 분류 1회 실행 후 종료 모드** (`python main.py --once`, `DOCUDOG_RUN_ONCE=1`: 큐에서 한 건 처리 후 종료; `skip_idle_wait_for_testing`과 조합 가능). — 2026-06-04
- **2. 업무 컨텍스트 묶음 (Context bundles / 시간 윈도우)** (`docudog/context_bundles.py`, watcher 큐 `(경로, 시각)`, `state.context_bundles`, `lineage_settings.context_bundles_*`, `DocuDog_lineage.md` 표). — 2026-05-19
- Stage 1 파이프라인: 감시 + 유휴 + 라우팅 + 텍스트 추출 + 로컬 LLM 분류 + `classification_report.md` + 선택적 `DocuDog_lineage.md` (파일명·해시 기반 pilot). — 2026-05
- 설정: `config.json` + YAML 오버레이 (`docudog/config_loader.py`), `model.backend` — `litert_lm` / `lm_studio` / `openai_compatible`. — 2026-05
- **Audit MVP + LLM** (`docudog/audit.py`): P1/P2 분류 시 `DocuDog_audit_log.md`에 행 추가; `audit_settings`로 켜기/끄기 및 `inference.audit_handling_suggestion` 기반 취급·공유 힌트(JSON). 경로: `paths.audit_log_path` 또는 리포트와 동일 폴더. — 2026-05
- **Lineage + LLM** (`docudog/lineage.py` + `docudog/inference.lineage_cluster_hints_batch`): `lineage_settings.llm_cluster_hints=true` 일 때 다중 파일 그룹별 관계 한 줄(한국어) 힌트 섹션 생성; `llm_max_hint_groups`, `llm_hint_max_tokens` 로 상한. — 2026-05
- **Lineage 유사도·Shadow Git 방향** (`docudog/lineage.py`): `lineage_settings.clustering` = `filename_key` | `similarity` | `both`(기본); 파일명 stem 정규화(`_v1`/`_최종`/`edit` 등) + `difflib.SequenceMatcher` + 요약 **Jaccard**; union-find로 그룹 병합; 파일 수 > `max_files_for_similarity` 이면 fuzzy 생략·로그. Mermaid 정렬은 `last_analyzed_utc` 우선. — 2026-05-19
- **소유자 태그/등급 재지정** (`docudog/owner_tags.py`, `DocuDog_tag_overrides.json`, `tools/sync_tag_overrides.py`): **웹이 아님** — 로컬 JSON; 안내 [docs/owner-tag-overrides.md](docs/owner-tag-overrides.md). 경로: `paths.tag_overrides_path` 또는 state 폴더. 재추론 없이 반영: `python tools/sync_tag_overrides.py` (과거 리포트 행은 미수정). — 2026-05
- **구동 직후 건전성 (경고만)** (`main._log_startup_environment_sanity`): `state_path`·`report_path` 부모 디렉터리 쓰기 프로브, watch 루트 존재, `use_mock` 아니고 HTTP 백엔드일 때 `GET /v1/models` 3s ( `DOCUDOG_SKIP_LM_MODEL_PROBE=1` 이면 스킵). — 2026-05-19
- **마지막 추론 출처** (`docudog/router` + `docudog/reporter`): 성공 분류 후 state 최상위 `last_inference_backend`, `last_inference_utc` 갱신; `classification_report.md` 말미 HTML 주석 블록 + `_Last inference: …_` 한 줄(이전 푸터 치환; `append_note`가 푸터 뒤에 붙은 내용은 보존). — 2026-05-19
