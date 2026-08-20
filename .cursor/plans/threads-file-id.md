# Plan: 문서 스레드 + 안정 file_id (260818-01 / 260818-02)

합의용. 구현 착수 전 이 문서를 기준으로 함.  
백로그: [to-do-list.md](../../to-do-list.md) `260818-01`~`260818-05`, `260805-02`.  
스레드만의 초안은 [doc-threads.md](doc-threads.md) — **이 파일이 우선**. 충돌 시 여기.

DocBank([kenn-io/docbank](https://github.com/kenn-io/docbank))에서 **패턴만** 가져옴. vault 복사·HTTP 쓰기·웹 UI는 비목표.

---

## 1. 한 줄

사람이 여는 화면은 `DocuDog_status`의 **최근 대화**(메일 스레드처럼). 기계는 `state.threads` + (가능하면) **경로와 분리된 `file_id`**. 에이전트는 MCP로 스레드/아이디를 질의. 원본 파일은 작업 폴더에 그대로 둠.

---

## 2. 왜 한 에픽인가

| 문제 | 지금 | 스레드만 하면 | file_id까지 |
|------|------|----------------|-------------|
| 과제 폴더에 ppt/docx가 쌓임 | 검색 10건, status에 최신본 Top만 | 폴더=대화로 보임 | rename 후에도 같은 대화 |
| 경로가 ID | state 키 = path | 멤버가 path라 이름 바꾸면 구멍 | DocBank node ID의 오버레이 변형 |
| 에이전트 | `docudog_search` | `docudog_thread` | path 또는 file_id |

1차는 **path 기반 스레드**로도 화면이 생김. 스키마는 처음부터 `members[].file_id`를 optional로 두고, `260818-02`를 같은 PR 또는 직후 PR로 넣는 걸 권장(두 번 마이그레이션 방지).

---

## 3. 비목표 (유지)

- Outlook/웹메일 앱, 서버 동기화, `.eml` 파싱
- 새 `DocuDog_threads.md`, lineage를 일상함으로 되돌리기 (`260731-20` 역할 분리)
- `classification_report.md` 스레드 단위 재작성
- DocBank CAS vault, 가상 트리, HTTP put/mv/rm, 웹/TUI
- 벡터 DB, 원본 파일 trash/GC
- MCP 쓰기 도구

후순위(이 플랜 밖, 백로그만): `260818-04` settle, `260818-05` 오버라이드 revision, `260818-D` Shadow Git.

이 플랜 **안**에 얇게 넣을 것: `260818-03` 중 `docudog_thread` + status digest의 `threads_top` (에러 코드 전면 개편·`by_hash`는 같은 에픽 2차 또는 다음 이슈).

---

## 4. 산출물

| 산출물 | 역할 |
|--------|------|
| `DocuDog_status.md` + `.html` | 최근 대화 Top N. MD=짧은 트리, HTML=`<details>` 접힘 |
| `DocuDog_state.json` | `threads[]`, 파일 레코드에 `file_id` |
| `DocuDog_lineage.md` | 보관. 나중에 thread id 교차만 |
| MCP | `docudog_status`에 `threads_top[]` + `docudog_thread(id \| path \| file_id)` |
| 모바일 digest | 후순위, 헤더 3개만 |

---

## 5. 데이터 계약

### 5.1 file_id (`260818-02`)

- 파일 메타(지금 path-keyed `files`/`entries`)에 `file_id: str` (UUIDv4, 한 번 발급하면 유지).
- **rename:** 같은 sha256, 짧은 시간(설정, 예: 24h) 안에 옛 path 사라지고 새 path 생기면 같은 `file_id`. 불확실하면 새 id + activity `[id_split]`.
- **내용 변경:** 같은 path(또는 추적된 rename)에서 sha256만 바뀌면 **같은 file_id**, 버전 헤드만 갱신.
- **삭제:** 원본은 안 옮김. state에 `gone_utc` tombstone 정도만(1차 생략 가능). 스레드 멤버에서 빠지거나 `missing` 표시.
- MCP `docudog_get`: `path` 또는 `file_id`.

마이그레이션: 기존 state 로드 시 id 없으면 발급해 저장. 리포트 과거 행은 수정하지 않음.

### 5.2 thread (`260818-01`)

`docudog/threads.py`가 분류/status 갱신 시 `state.threads` 재계산 (lineage처럼 전체 재생성).

```text
thread:
  id            # "ver:" + lineage_group_key  또는  "conv:" + 정규화 폴더
  kind          # version | conversation | mixed
  title
  latest_path
  latest_file_id
  last_utc
  member_count
  today_n
  max_security
  members[]     # path, file_id, sha12, utc, summary, security_level, role
                # role: latest | version | peer
```

묶기 (1차, LLM 없음):

- **version:** 기존 `_build_multi_groups` (filename_key + similarity), 멤버 ≥2.
- **conversation:** watch 하위 폴더, 서로 다른 lineage 키 ≥2, context_bundle 또는 태그 교집합. 폴더 깊이 하한(Documents 루트 금지), 멤버 상한(예: 12).
- **mixed:** version 그룹이 conversation에 들어가면 헤더는 폴더, 펼침에 버전 서브리스트.

정렬: `last_utc` 내림차순. 한 줄: 최신 summary 또는 `last_change_summary`.

설정 초안: `thread_settings.enabled` (기본 true), `max_threads`, `max_members`, `include_conversations`.

---

## 6. 구현 단계

### P0 — file_id 최소 + 스레드 받은편지함

1. state 파일 레코드에 `file_id` 발급/유지. rename 휴리스틱은 **간단 버전**(동일 hash, 직전 분류 목록에서 path만 다름)이면 충분.
2. `threads.build_threads(state, config)` → `state["threads"]` (상위 N, 기본 20).
3. `status_dashboard`: 「권장 최신본」+「같이 볼 후보」를 **「최근 대화」로 통합**하거나 위에 두고 구 섹션 축소.
4. HTML `<details>`, MD 짧은 트리. 헤더 8~12, 펼침 멤버 8.

### P1 — MCP

- `docudog_status` digest에 `threads_top[]`.
- `docudog_thread(id | path | file_id)`.
- `docudog_get`에 `file_id` 인자(또는 path와 상호 배타).
- 에러는 짧은 `code` 필드부터 (전면 개편은 `260818-03` 나머지).

### P2 — 계약 보강 (같은 에픽 또는 바로 다음)

- `docudog_by_hash`.
- excerpt에 `sha256` / `truncated`.
- `260805-02` 컨텍스트 팩은 스레드 멤버 MD 묶음과 맞출 것.

리포트 행에 thread title은 **선택, 본진 아님**.

---

## 7. 리스크

- **과병합:** 대화는 폴더 깊이로 가둠.
- **중복 UI:** status에서 스레드가 이김.
- **P1 섞임:** 헤더 `max_security`. excerpt는 기존 `mcp_settings`.
- **rename 오탐:** 같은 해시 사본이 두 폴더에 있으면 id를 합치지 않음(복제는 related/해시 조회).
- **재계산:** lineage와 동일 `max_files_for_similarity` 상한.

---

## 8. 확인

1. `제안서_v1.docx` / `제안서_최종.docx` → 버전 스레드 1, 헤더는 최종.
2. Edge AI 과제 폴더 pptx+docx+xlsx → 대화 스레드 1, 폴더명 제목.
3. Desktop 무관 파일은 스레드 안 탐.
4. 파일 이름만 변경(해시 동일) → 같은 `file_id`, 스레드 멤버 유지.
5. 일상은 `DocuDog_status.html`만. MCP로 그 대화 멤버가 검색 10건보다 낫다.

---

## 9. 손대지 않는 DocBank 조각

Watcher settle(`260818-04`), 오버라이드 If-Match(`260818-05`), 검증 백업(`260818-D`)은 이 플랜 머지 후 별 이슈.
