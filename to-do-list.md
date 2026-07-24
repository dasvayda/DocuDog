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
  **보강 (LLM-Wiki에서 유효한 부분만):** hash 변경 시 **이전 `state.summary` + delta**로 재작성; `summary_history[]`(SHA·utc) 보존 — model-collapse 왜곡 완화.

- **5. 공유 폴더·NAS(UNC) 감시·확장 검증**  
  **왜:** 노트북 단독을 넘어 `\\NAS\…` 또는 마운트된 네트워크 드라이브를 `watch_settings.target_directories`에 넣었을 때 팀 자료가 같이 정리되는지 검증.  
  **방향:** Windows **UNC·네트워크 경로**에서 `watchdog` 관찰이 안정적인지 재현·보완; **다중 사용자·동시 저장** 시 큐/상태가 꼬이지 않도록 **잠금·재시도·단일 리포트/단일 state** 정책 명확화(필요 시 파일 잠금 또는 큐 직렬화).

- **6. 규칙 엔진 + LLM 하이브리드(P1~P4·Audit 신뢰도)**  
  **왜:** 등급을 LLM에만 맡기면 “왜 P1?”·“왜 스킵?” 같은 내부 테스트 시 신뢰 이슈가 난다.  
  **방향:** `config.json`(또는 YAML)에 **정규식·키워드 리스트**(사내 프로젝트 코드, 고객명, 주민번호 패턴 등)를 두고, `router`/`inference`에서 **1차 매칭** 후 분류 프롬프트에 **힌트·가이드**(예: 민감 키워드 포함 시 상위 등급 후보)를 주는 하이브리드. 룰 적분·설명 로그(리포트 또는 state 메타)까지 범위 정하기.

**참고 — [GeekNews #28208](https://news.hada.io/topic?id=28208) (Karpathy LLM-Wiki)에서 DocuDog에 맞는 것만 추린 항목**  
LLM-Wiki는 **사용자가 질의하는 개인/팀 위키**(Obsidian + 에이전트 ingest/query/lint)다. DocuDog Stage 1은 **UI 없는 백그라운드 watcher** — 감시·분류·등급·감사·**문서 DNA(lineage)** 가 본체이다. query·entity 위키·index 검색 등은 **보류 C**로 옮김.

- **7. 처리 이벤트 로그 `DocuDog_activity_log.md` (운영 가시성)**  
  **왜 DocuDog에 맞음:** MVP에 UI가 없어 “오늘 뭐가 돌았는지”가 안 보인다. 기존 `DocuDog_audit_log.md`(P1/P2 전용)와 **역할 분리** — 전 이벤트 타임라인.  
  **방향:** `[classify]`, `[skip_hash]`, `[skip_filter]`, `[audit]`, `[lineage]` 접두사로 append-only 한 줄. `grep`/tail로 최근 처리 확인.  
  **아닌 것:** LLM-Wiki의 `[query]`·위키 ingest 로그 전체를 베끼는 것.

- **8. 거버넌스 무결성 점검 (state/lineage lint, 경량)**  
  **왜 DocuDog에 맞음:** Audit·lineage가 **통제 레이어** — P1/P2인데 audit 행 없음, lineage 그룹 내 summary·등급 상충, context bundle과 state 불일치 등은 **거버넌스 버그**에 가깝다.  
  **방향:** `tools/lint_governance.py` 또는 idle 시 주기 실행 → `DocuDog_lint_report.md`. **원본 파일은 읽기만**, 수정 금지. LLM 호출은 선택(규칙 기반만으로도 1차 가능).  
  **아닌 것:** “고아 위키 페이지”, “엔티티 페이지 누락” 같은 PKM 린트.

**목표(사용자 가치 재정리, 2026-07-22):** 아래 3개는 "어떻게 표시할지"가 아니라 "리포트가 무엇을 보여줘야 사용자가 어떤 발견·경고·판단을 얻는가"로 먼저 정한 것. 실제 `classification_report.md`/`DocuDog_audit_log.md` 관찰 근거를 포함. 6번(규칙 엔진 하이브리드)과 문제의식은 같지만 역할이 다름 — 6번은 "정확도를 올리는 법", 9번은 "지금 정확하지 않을 수 있음을 사용자에게 투명하게 알리는 법".

- **9. 보안 등급 신뢰성 노출 — 직관적 라벨 + 판단 근거 (경고성 인사이트)**  
  **발견:** `classification_report.md` 실제 데이터에서 65번째 행(백엔드가 `lite_rt` → `mock`/`openai`로 전환된 시점)을 기점으로 **그 이전은 전부 P1, 이후는 전부 P2**로 몰림. 파일 내용의 민감도가 우연히 그 시점에 갈렸다기보다, **등급이 파일 내용보다 어느 백엔드가 처리했는지에 좌우될 수 있음**을 시사. `security_level`은 규칙 엔진 없이 모델이 매번 판단하는 값이라(`docs/implemented-features.md`) 고정 기준이 없다는 게 원인 후보.  
  **사용자 가치:** "이 파일이 P1이다"라는 사실보다, **"이 등급을 근거로 삭제·공유 판단을 내려도 되는가"**에 대한 신뢰. 지금은 이 신뢰를 줄 수 없다는 사실 자체를 먼저 알려주는 것이 핵심 가치.  
  **쉬운 UI 방향:** 표의 `P1` 기호 앞에 사람이 읽는 라벨을 먼저 노출, 기호는 괄호/뱃지로 뒤에(예: `매우 민감 (P1)`). 라벨 사전은 config로 노출해 조직이 재정의 가능하게. 등급 옆에 **어느 backend가 판단했는지**(이미 있는 Inference 열과 나란히)를 붙여, 사용자가 "이 등급 신뢰도"를 스스로 가늠할 신호를 줌.  
  **구현(방향):** `docudog/reporter.py`(표 렌더링), `config.json`에 `security_level_labels` 같은 매핑 테이블 추가; 리포트 최상단에 "등급별 backend 분포" 같은 경고 요약도 함께 고려(9번·6번과 연결).

- **10. 미분류 사각지대 경고 — “놓친 파일” 하이라이트 (발견/경고)**  
  **발견:** 현재 MVP는 `.pdf` 등 텍스트 추출 미구현 확장자를 조용히 스킵만 하고(리포트 하단 인용 블록), 실제 스킵 목록에는 `주민등록등본`, `졸업증명서` 같은 개인정보 문서가 다수 포함되어 있는데도 아무 경고가 없음.  
  **사용자 가치:** "분류된 파일의 등급"보다 **"분류조차 되지 않은, 어쩌면 더 민감한 파일이 있다"**는 사실 자체가 더 중요한 정보일 수 있음.  
  **쉬운 UI 방향:** 리포트 최상단에 한 줄 경고 배너, 예: `⚠ 미분류 32건(텍스트 추출 미지원) — 그중 6건은 파일명에 개인정보 관련 키워드 포함`. 상세는 접어두고 배너만 먼저 보이게.  
  **구현(방향):** 기존 스킵 로그(`reporter.py`의 append_note 경로)에 파일명 키워드 매칭(주민등록, 졸업증명서, 계약서, 이력서 등 가벼운 규칙)만 추가해 집계. 새 로그 불필요, 기존 데이터 재활용.

- **11. 실행 요약 & 액션 다이제스트 — “그래서 지금 뭘 해야 하나” (가치 압축)**  
  **발견:** `DocuDog_audit_log.md`의 handling hint(`[sharing: internal_only]`, `[sharing: redact_before_external]`)는 이미 존재하지만 100행짜리 표 안에 묻혀 아무도 보지 않음.  
  **사용자 가치:** 로그 열람이 아니라 **압축된 다음 행동 리스트** — "외부 공유 전 확인 필요 N건", "등급 불일치 의심 재검토 M건" 등.  
  **쉬운 UI 방향:** 리포트/감사로그 최상단에 3~5줄짜리 다이제스트 카드(표는 그 아래 상세용으로 유지). 신규 파일 없이 기존 두 문서 상단만 수정.  
  **구현(방향):** `docudog/audit.py` 집계 로직 재사용, `reporter.py` 헤더 생성부에 요약 카드 삽입.

**목표(모바일·로컬 LLM 사용자, 2026-07-24):** PC 백그라운드 watcher와 별 레인. 공통 코어(추출→분류→등급→로컬 산출물)는 재사용하되, **공유·배터리·짧은 확인 UI**가 모바일에서 사용 빈도·만족도를 좌우한다. 전용 네이티브 앱 전체가 아니라 **Share/다운로드 진입점 + 전력 게이트 + 한 화면 요약** 3축만 Stage 2 후보로 적는다.

- **12. 공유·다운로드 직후 1회 분류 (Share-to-classify)**  
  **빈도·만족:** 모바일 local LLM 사용자의 문서 유입은 **카톡·메일·브라우저 “저장/공유”**가 대부분(일 수십 회). 저장 직후 **P-level·태그·한 줄 summary**를 보는 순간 만족도가 가장 크고, “잘못된 채팅방에 P1을 붙여넣기 전에 막았다”는 체감과 직결.  
  **DocuDog화:** Android Share Target / iOS Share Extension(또는 1단계로 **Downloads·Inbox 감시 + `classify_one` 1회**) → 기존 `docudog/single_file.py` 파이프라인. 산출: `classification_report` 행 + **`DocuDog_last_classify.json`**(경로·등급·summary·utc)로 다른 앱/단축어가 읽기. 클라우드 업로드·채팅 전송 **전** 로컬에서만 판단.  
  **확인:** 공유로 PDF/txt 저장 → 30초 내 last_classify json 갱신·등급 표시(알림 또는 Files 미리보기).  
  **범위:** Windows `main --file` 패턴 검증 후 모바일 companion; 채팅형 LLM UI는 만들지 않음.

- **13. 충전·배터리·발열 게이트 (Power-aware idle)**  
  **빈도·만족:** 모바일 local LLM은 **매일 백그라운드**를 쓰지만 배터리·발열 불만이 이탈 1순위. “충전 중·화면 꺼짐·배터리 N% 이상일 때만 추론”이 있으면 **신뢰·재설치율**이 올라감(사용 빈도는 passive지만 **만족도 기여가 큼**).  
  **DocuDog화:** `idle_settings` 확장 — `min_battery_percent`, `require_charging`, `defer_on_thermal_throttle`(OS API 또는 휴리스틱). 큐는 쌓되 LiteRT/Gemma 추론만 게이트; hash 스킵·규칙 1차 매칭(#6)은 저전력으로 선행 가능. Windows 노트북(배터리 모드)에도 동일 키 재사용.  
  **확인:** 배터리 20%·미충전 시 큐 적재만, 충전+유휴 시 처리; activity log에 `[defer_power]` 기록.  
  **범위:** `docudog/watcher.py` + config; Android/iOS는 WorkManager/BGTask로 동일 정책 매핑.

- **14. 모바일 한 화면 다이제스트 (`DocuDog_mobile_digest.html` 또는 json)**  
  **빈도·만족:** local LLM 사용자는 **결과를 자주 열람**(하루 여러 번)하지만 `classification_report.md` 표는 폰에서 읽기 어렵다. **3~5줄 + P1/P2 건수 + 미분류 경고(#10 연동)** 만 있는 단일 파일이면 Files/브라우저·홈 위젯/단축어로 **짧게 확인** 가능 — #11 데스크톱 다이제스트의 **모바일 뷰포트 버전**.  
  **DocuDog화:** 분류·audit·스킵 집계 후 **갱신되는 경량 HTML**(또는 json) 1파일; 사용자가 이미 쓰는 **로컬 동기화 폴더**(iCloud/Drive/Synology)에 출력 — DocuDog 서버 없음. 상단: “오늘 P1 n건 · 미분류 m건 · 마지막 추론 backend”; 탭하면 기존 리포트 링크(선택).  
  **확인:** 폰 브라우저에서 digest만 열어 당일 P1·미분류 숫자가 맞는지; 새 공유 파일(#12) 후 digest 갱신 지연 측정.  
  **범위:** `docudog/reporter.py` 또는 소형 `render_mobile_digest()`; #9·#10·#11과 데이터 공유, UI는 digest 전용.

**모바일 3종 우선순위:** #12 공유 직후 분류(체감 가치) → #13 전력 게이트(유지 만족) → #14 digest(재방문 빈도).

---

### 보류 (Deferred)

나중에 구현 검토. **모델 A/B 비교·벤치** 용도는 MVP 본류가 아니므로 여기 보관합니다.

- **C. LLM-Wiki 계열 — DocuDog Stage 1과 **제품 목표 불일치** (억지 매핑 제거, 2026-06-04)**  
  [GeekNews #28208](https://news.hada.io/topic?id=28208)에서 DocuDog watcher·거버넌스와 **다른 레인**인 아이디어. master-plan의 **서버 RAG Graph·벡터 DB** 단계에서 다시 검토할 때 참고만.

  | 아이디어 | 왜 Stage 1 아님 |
  |----------|-----------------|
  | `DocuDog_index.md` 카탈로그 | `classification_report.md` + `DocuDog_state.json`과 **중복**; “위키 목차”가 아니라 리포트가 이미 산출물 |
  | `tools/query_docs.py` (자연어 Q&A) | **질의형 PKM**; DocuDog은 사용자 질의 없이 **백그라운드 분류**. RAG Graph는 로드맵이지만 서버/그래프 맥락 |
  | `DocuDog_entities/*.md` 롤업 | **엔티티 위키**; DocuDog DNA는 **문서 버전 lineage**, Tolkien Gateway식 개념 페이지 아님 |
  | `tools/search_index.py` (BM25) | 로드맵 LanceDB/Chroma와 **같은 축**; watcher MVP 선행 과제 아님 |

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
