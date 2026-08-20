# DocuDog Features

사용자가 **무엇을 얻고, 어디를 보면 되는지** 기준으로 정리한 기능 목록임.  
모듈·설정 키 단위 인벤토리는 [docs/implemented-features.md](docs/implemented-features.md).  
제품 철학·로드맵은 [master-plan.md](master-plan.md).

---

## 지향점

**사람은 파일을 아무 데나 쌓아도 되고, 정리는 뒤에서 AI가 한다.**

- 폴더 규칙을 강요하지 않음. 원본은 작업하던 자리에 그대로 둠.
- 클라우드에 문서를 올리지 않음. 분류는 **이 PC(또는 지정한 로컬 모델 서버)** 에서 함.
- 웹앱이 아님. 일상 입구는 **Cursor/Claude MCP**(또는 트레이). status.md는 `.docudog/` 안 옵션 산출물이며 강제 오픈하지 않음.

오늘 구현의 범위는 Stage 1 **Watcher**: 지정 폴더를 감시하고, 한가할 때 읽고, 태깅·등급·요약을 붙인 뒤 로컬에 쌓음.

---

## 하루 흐름 (사용자)

1. 평소처럼 Word/PPT/HWP를 저장함.
2. PC가 잠깐 비면 DocuDog이 새·바뀐 파일을 분류함.
3. **먼저 묻는 곳:** Cursor/Claude에서 DocuDog MCP (`docudog_search` / `docudog_get_lineage`).  
   기계 산출물은 `%USERPROFILE%/.docudog/` (status.md는 그 안, 열 필요 없음).
4. P1이면 트레이 토스트가 짧게 뜨고, audit 로그에 남음.
5. Cursor/Claude에서는 MCP로 “이 과제 최신 덱”처럼 **이미 분류된 코퍼스**를 질의함.

원본을 옮기거나 이름을 강제 변경하지 않음.

---

## 1. 조용히 따라가기 (수집)

업무 중에 CPU를 뺏지 않고, 저장한 파일을 놓치지 않게 함.

| 기능 | 사용자에게 보이는 것 |
|------|----------------------|
| 폴더 감시 | `watch_settings.target_directories` 아래 생성·수정이 큐에 쌓임. 시작 시 기존 파일도 한 번 훑음. |
| 유휴 처리 | 타이핑 중이면 미루고, 입력이 끊기면 처리. 프로세스 우선순위는 낮춤. |
| 배터리 게이트 | 충전/잔량 조건이 안 되면 추론만 미룸. 큐는 유지. |
| 같은 내용 스킵 | 파일이 안 바뀌었으면(SHA-256 동일) LLM을 다시 안 돌림. |
| 공유 폴더 | UNC/NAS 경로 감시, 잠긴 파일은 재시도. state/리포트는 **한 세트**가 원칙. |
| 한 건만 돌리기 | `python main.py --file 경로` — 워처 없이 그 파일만 분류. |
| 트레이 (선택) | `python main.py --tray`. MCP 설정 쓰기, `.docudog` 열기, 일시정지. status.md는 안 염. `--install-startup`으로 시작프로그램 바로가기. |

**아직 아님:** 메일 첨부·USB를 OS 커널에서 가로채기, 파일이 아직 다운로드 중인 settle 대기.

---

## 2. 이게 무슨 문서인지 (분류)

사람이 이름·폴더를 안 맞춰도, 내용 기준으로 라벨을 붙임.

| 기능 | 사용자에게 보이는 것 |
|------|----------------------|
| 본문 추출 | `.txt` `.md` `.docx` `.pptx` `.xlsx` `.hwp` `.hwpx` `.pdf`(텍스트 레이어). 암호·스캔 PDF는 스킵. |
| 자동 태깅 | 키워드 태그 + 한 줄 요약. |
| 보안 등급 | P1(매우 민감) ~ P4(일반). 표에는 사람용 라벨이 먼저 보임. |
| 업무 함 | 팀이 정한 카테고리(계약/회의록 등)로 한 칸에 맞춤. 자유 태그와 별개. |
| 규칙 힌트 | 주민번호 패턴·“계약서” 같은 키워드가 있으면 등급을 올리도록 모델에 힌트. |
| 내가 고침 | `DocuDog_tag_overrides.json`으로 태그/등급을 덮어씀. 웹 UI 없음. |
| 모델 위치 | 로컬 LiteRT, LM Studio, 또는 개발용 OpenAI 호환. 안 되면 mock으로라도 파이프는 돌아감. |

**신뢰 주의:** 등급은 조직 공인 DLP가 아님. 모델·백엔드가 바뀌면 분포가 흔들릴 수 있음. status에 그 경고가 있음.

---

## 3. 같은 일 · 최신본 찾기 (맥락)

`_v1`, `_최종`, 같은 폴더의 PPT+표처럼 **흩어진 저장**을 한 묶음으로 봄.

| 기능 | 사용자에게 보이는 것 |
|------|----------------------|
| 최근 대화 (스레드) | status에서 메일처럼 최신이 한 줄. HTML은 펼치면 이전 파일. 버전 묶음과 과제 폴더 대화를 구분. |
| 안정 id | 파일 이름만 바뀌어도(내용 같음) 같은 문서로 추적. |
| 같이 볼 후보 | 방금 분류한 파일과 가까운 이전 버전·참고 파일 경로. |
| 시간창 묶음 | 비슷한 시각·같은 폴더에 떨어진 파일 (context bundle). lineage 보관본에 표. |
| 한 줄 변경 | 같은 파일 재분류뿐 아니라 `_v1`/`_최종`처럼 **다른 파일명** 계보에서도 직전 vs 최신 한 줄. MCP `docudog_get_lineage`. |
| 계보 보관 | `DocuDog_lineage.md` — 그룹 전체·해시. **매일 여는 화면이 아님.** |

새 `DocuDog_threads.md`는 없음. 일상 질의는 MCP. status.md는 `.docudog/` 안 옵션.

---

## 4. 민감하면 알려주기 (거버넌스)

유출을 **차단**하지는 않음. 대신 “이건 조심”을 남기고, 분류가 안 된 구멍을 보여 줌.

| 기능 | 사용자에게 보이는 것 |
|------|----------------------|
| P1/P2 감사 로그 | `DocuDog_audit_log.md`에만 민감 건. 공유 전 확인 같은 handling 힌트. |
| 지금 할 일 | status 상단: 외부 공유 전 확인할 건, 주기 문서 미작성 등. |
| 미분류 경고 | 암호·스캔 PDF처럼 못 읽은 파일, 파일명에 주민등록·졸업증명 같은 단어. |
| 주기 문서 | “이번 주 주간보고가 없다”처럼 **없는 파일**을 cadence 규칙으로 알림. |
| 거버넌스 lint | state와 audit가 어긋난지 점검. 원본 파일은 안 고침. |

**아직 아님:** 메일 발송 차단, 실시간 DLP, 파일을 vault로 옮기기.

---

## 5. 오늘 뭘 보면 되나 (현황·기록)

역할이 다른 산출물을 섞지 않음.

| 여는 파일 | 역할 |
|-----------|------|
| **`DocuDog_status.md` / `.html`** | **기본 진입점.** 오늘 건수, 할 일, 최근 대화, 경고. |
| `DocuDog_mobile_digest.html` | 폰에서 볼 짧은 요약 (같은 숫자의 축소판). |
| `classification_report.md` | 분류 **이벤트 로그** (한 줄씩 append). |
| `DocuDog_activity_log.md` | 오늘 워처가 뭘 했는지 (`classify` / `skip_*` / `defer_*`). |
| `DocuDog_audit_log.md` | 민감 건만. |
| `DocuDog_lineage.md` | 보관·디버그. |
| `DocuDog_last_classify.json` | 방금 분류 1건 (다른 앱/단축어가 읽기). |
| `DocuDog_state.json` | 기계용 진실. 사람이 매일 편집할 파일 아님. |

HTML은 해당 MD와 **같은 이름**. 브라우저로 status를 열면 스레드를 접을 수 있음.

---

## 6. AI에게 물어보기 (MCP)

문서를 채팅에 다시 첨부하지 않고, **이미 분류된 메타**를 질의함.

| 도구 | 쓰는 순간 |
|------|-----------|
| `docudog_status` | 오늘 뭐가 돌았나, 최근 대화 요약. |
| `docudog_search` | 태그·P등급·요약으로 찾기. `since`/`until`(UTC 날짜) 가능. |
| `docudog_get` | 한 파일 메타. 경로 또는 `file_id`. 본문 발췌는 기본 P4만. P1/P2는 `excerpt_blocked_p1`. |
| `docudog_get_lineage` | 그 과제 **최신 경로** + 멤버 타임라인 + 한 줄 변경. |
| `docudog_get_context_bundle` | 같이 볼 경로 + 시간창 묶음. |
| `docudog_thread` | 검색 10건 대신 **그 과제 대화의 파일들**. |
| `docudog_related` | 이 파일과 같이 볼 것. |
| `docudog_by_hash` | 같은 바이트가 어디에 또 있나. |
| `docudog_last_classify` / `recent_changes` | 방금 분류, 최근 내용 변화. |

연결: [docs/mcp-connect.md](docs/mcp-connect.md). 읽기 전용. P1/P2 원문을 MCP로 열어 두지 않음.

---

## 7. 이 PC에서 버티기 (운영)

| 기능 | 사용자에게 보이는 것 |
|------|----------------------|
| 단일 실행 | 같은 DocuDog을 두 번 켜면 이전 인스턴스를 정리. |
| 설정 | `config.json` + 선택 YAML 오버레이. 비밀은 `.env`. |
| 시작 점검 | 출력 폴더 쓰기, watch 경로, 모델 서버 연결 — **경고만** (시작을 막지 않음). |
| 추론 출처 | 리포트·state에 마지막 백엔드(lite_rt / lm_studio / mock 등). |
| 트레이 | `python main.py --tray` (선택). CLI 워처는 그대로 `python main.py`. |

---

## 이 제품이 아닌 것

사용자 점검 때 기대치를 맞추기 위함.

- 파일 탐색기/웹 드라이브 **대체** 또는 폴더 자동 이동
- 스캔 PDF OCR, 벡터 의미검색, MCP SSE 서버
- 메일·메신저로 나가는 파일 **차단**
- 클라우드 동기화, 다중 사용자 실시간 협업
- “어제 버전으로 파일 복원” (Shadow Git은 로드맵)
- 전사 서버 RAG / 벡터 DB 검색 (로컬 메타 검색·MCP만)

---

## 관련 문서

| 문서 | 독자 |
|------|------|
| 이 파일 | 기능·가치 점검 (사람) |
| [docs/docudog-output-spec.md](docs/docudog-output-spec.md) | 산출물을 읽는 에이전트·스크립트 |
| [docs/implemented-features.md](docs/implemented-features.md) | 코드에 있는 동작·모듈 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 데이터 흐름 |
| [to-do-list.md](to-do-list.md) | 다음 할 일 |
