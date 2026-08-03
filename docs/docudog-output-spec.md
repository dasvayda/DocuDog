# DocuDog output agent spec

이 문서는 **DocuDog가 로컬에 쓰는 산출물을 읽는** 스크립트·에이전트용이다.  
DocuDog **소스/설정 개발** 가이드는 저장소 루트 [`AGENTS.md`](../AGENTS.md)를 본다 (목적·독자가 다름).

기본 위치는 `paths.report_path` / `paths.state_path` 부모 폴더다. 예: `%USERPROFILE%/Documents/DocuDog/`.

---

## 산출물 한눈에

| 파일 | `paths.*` / 기본 | 역할 | 갱신 |
|------|------------------|------|------|
| `DocuDog_state.json` | `state_path` | 기계 진실 소스 (파일별 해시·태그·등급·요약) | 분류·hash 스킵 시 |
| `DocuDog_status.md` (+ `.html`) | `status_path` (빈 값이면 report 옆) | **현황 대시보드** (짧게) | 분류/스킵/시작 시 |
| `classification_report.md` (+ `.html`) | `report_path` | 분류 이벤트 표 + 스킵 노트 | append |
| `DocuDog_activity_log.md` | `activity_log_path` | 운영 타임라인 `[classify]` 등 | append |
| `DocuDog_audit_log.md` | `audit_log_path` | **P1/P2만** 감사 + handling hint | append |
| `DocuDog_lineage.md` | `lineage_settings.output_path` | **보관·상세** 그룹/(선택) Mermaid | 재생성 |
| `DocuDog_mobile_digest.html` (+ `.json`) | `mobile_digest_path` | 모바일 한 화면 요약 | status 갱신 시 |
| `DocuDog_last_classify.json` | `last_classify_path` | 최근 1건 분류(공유 직후 companion) | 분류 성공 시 |
| `DocuDog_tag_overrides.json` | `tag_overrides_path` | 소유자 태그/등급 덮어쓰기 | 수동/도구 |

권장 사용자 진입점: **`DocuDog_status.md`** (또는 동일 basename `.html`).  
상세 추적: report / activity / audit / lineage.

---

## `DocuDog_state.json`

- 최상위: `version`, `files`, `last_inference_backend`, `last_inference_utc`, 선택 `ops`, `context_bundles`
- `files[<abs_path>]`: `sha256`, `last_analyzed_utc`, `last_checked_utc`, `summary`, `tags`, `security_level` (`P1`–`P4`), `model_tags`, `model_security_level`, `owner_override`, `inference_source`, `inference_reason`
- `ops` (스킵 인사이트): `skip_extract_count`, `skip_extract_sensitive_count`, `skip_extract_by_reason`, `skip_extract_sensitive_recent[]`

**신뢰도:** `security_level`은 규칙 엔진 없이 모델 출력(+선택 owner override). backend가 바뀌면 등급 분포가 흔들릴 수 있음 — status 대시보드에도 경고 문구 있음.

---

## `classification_report.md` / `.html`

- 표 열: Analyzed At | File | SHA-256 | Tags | **Security**(라벨+코드, 예: `매우 민감 (P1)`) | Inference | Summary
- 상단 선택 배너: `<!-- docudog-banner:start -->` … 미분류/민감 파일명 경고
- 말미: `<!-- docudog-meta:start -->` `_Last inference: …_`
- `>` 인용 노트: 추출 스킵 등
- HTML은 MD와 **동일 basename**, append/시작 시 동기화

라벨 매핑: config `security_level_labels` (기본 P1=매우 민감 … P4=일반).

---

## `DocuDog_activity_log.md`

한 줄: `[로컬시각] [prefix] message`  
주요 prefix: `classify`, `skip_hash`, `skip_filter`, `skip_extract`, `skip_empty`, `defer_active`, `defer_yield`, `defer_power`, `cadence_miss`, `audit`, `status`  
(`lineage`는 `activity_settings.log_lineage: true`일 때만)

---

## `DocuDog_audit_log.md`

P1/P2만. Handling hint 셀 예: `… [sharing: internal_only|redact_before_external|ok_external]`

---

## `DocuDog_status.md`

오늘 분류 수, **지금 할 일(다이제스트)**, 주기 문서 cadence, P1/P2, 미분류 스킵·민감 키워드, 등급별 backend 분포, 다중버전 그룹 권장 최신본 Top, 최근 유사·맥락 후보, 상세 파일 경로 링크.  
`.html` 동기화는 report와 동일 로직.

## `DocuDog_mobile_digest.html` / `.json`

status의 뷰포트 축소판. 오늘 분류·P1/P2·미분류·액션·cadence miss. `mobile_digest_settings.enabled`(기본 true).

## `DocuDog_last_classify.json`

최근 성공 분류 1건: `path`, `basename`, `security_level`, `tags`, `summary`, `inference_source`, `sha256`, `utc`, 선택 `category_ids`, `change_summary`.

## 업무 카테고리 (`category_settings` + `DocuDog_categories.json`)

`enabled: true`일 때 분류 프롬프트에 선택지·샘플 요약 주입. 결과 `state.files[].category_ids` (미매칭=`uncategorized`). 예: `DocuDog_categories.example.json`.

## 시맨틱 변경 (`semantic_settings`)

hash 변경 재분류 시 `summary_history[]`, `last_change_summary`. `llm_change_summary: true`면 aux LLM 한 줄(기본 off=휴리스틱).

## UNC/NAS 감시

`watch_settings.file_open_retries` / `event_dedupe_seconds`. 경로는 UNC 유지. **단일** state/report 인스턴스 권장.

## 규칙 힌트 (`rule_settings`)

`enabled: true`일 때 키워드/정규식 매칭 → 분류 프롬프트 힌트 + 등급 floor(`state.files[].rule_floor`). owner override가 있으면 floor 미적용.

## 도구

- `python tools/lint_governance.py` — 거버넌스 린트 리포트
- `python tools/search_corpus.py --level P1 --query 키워드` — state 메타 검색

---

## `DocuDog_lineage.md`

일상 열람용이 아니라 **보관·감사·디버그**. 현황은 status를 본다.  
기본은 Mermaid off (`include_mermaid: false`); 싱글톤 목록은 `include_singleton_list`.

---

## 설정 키 (요약)

- `paths.activity_log_path`, `paths.status_path`, `paths.mobile_digest_path`, `paths.last_classify_path`
- `activity_settings.enabled`, `activity_settings.log_lineage`
- `status_settings.enabled`, `mobile_digest_settings.enabled`
- `cadence_settings` (rules: pattern / weekly|monthly)
- `idle_settings.min_battery_percent`, `require_charging`, `defer_on_thermal_throttle`
- `lineage_settings.include_mermaid`, `include_singleton_list`, `slim_intro`
- `skip_insight_settings.sensitive_filename_keywords`
- `security_level_labels`
