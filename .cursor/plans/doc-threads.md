# 문서 스레드 (메일 Conversation 뷰)

**상위 플랜:** [threads-file-id.md](threads-file-id.md) (`260818-01` + `260818-02`). 이 파일은 스레드 UX 초안. 충돌 시 상위 플랜이 이김.

기획 검토 + 구현 방향. 구현 착수 전 합의용.  
비유: iPhone 메일 / Outlook이 **같은 대화를 한 줄로 접고**, 펼치면 시간순 메시지가 나오는 것.

---

## 1. 사용자가 실제로 원하는 것

분류 리포트처럼 **이벤트가 한 줄씩 쌓이는 것**은 받은편지함을 “대화 묶기 끔”으로 보는 것과 같음.  
사람은 이렇게 물음:

- 이 주제(과제/제안서/견적)의 **지금 유효한 최신**이 뭔가
- 그 아래에 **이전 버전·같이 만든 PPT/표**가 붙어 있나
- 펼치면 **시간순으로** 뭐가 바뀌었나 (한 줄이면 충분)

Edge AI PPT 참고 목록을 MCP로 뽑을 때도, 검색 10건이 아니라 **폴더 하나 = 대화 하나**로 보이면 판단이 빨라짐.

### 메일에 있는 것 / DocuDog에 없는 것

| 메일 | DocuDog 오늘 | 갭 |
|------|----------------|-----|
| `In-Reply-To` / Conversation-ID | 파일명 stem, 요약 Jaccard, 시간창 번들 | ID가 헤더가 아니라 **추론** |
| 제목 `Re:` 정규화 | `lineage_group_key` (`(1)`, `_최종`, `_v1`) | 폴더·태그가 다른 파일은 안 묶임 |
| 최신 메일 = 스레드 헤더 | status 「권장 최신본」은 **파일명 키만**, Top 8 | 유사도 클러스터·번들은 헤더에 안 나옴 |
| 펼치면 이전 메일 | lineage.md 전체 표 (일상 비목표) | 접힘 UI 없음 |
| 안읽음 | **열람 신호 없음** | “오늘 이 스레드에 분류된 건”으로 대체 |

열람/클릭 추적은 Stage 1 범위 밖. 스레드의 “새 것”은 `last_analyzed_utc`가 오늘인 멤버 수.

---

## 2. 이미 있는 세 묶음 (새로 발명하지 말 것)

1. **버전 스레드** — `lineage.py`: 복사본·`_v1`/`_최종` + (옵션) 요약 Jaccard union-find. DNA/버전.
2. **대화 스레드** — `context_bundles.py`: 같은 시각±N분, 같은 폴더에 같이 떨어진 파일. 메일 “첨부 여러 개”.
3. **이웃 힌트** — `related_docs.py`: 방금 분류한 **앵커 1개**의 Top N. status 「이 파일과 같이 볼 후보」. 받은편지함 전체가 아님.

제품 공백은 **알고리즘 부족**이 아니라 **받은편지함 뷰가 없음**. 데이터가 lineage/status/related에 흩어져 있고, 접힌 대화로 안 보임.

---

## 3. 비목표

- Outlook/웹메일 UI 앱, 서버 동기화
- 새 벡터 DB
- `classification_report.md`를 스레드 단위로 재작성 (append-only 감사 로그 유지)
- `DocuDog_lineage.md`를 일상 받은편지함으로 되돌리기 (`260731-20` 역할 분리 유지)
- 이메일 `.eml`/Outlook 본문 파싱 (별 에픽)

---

## 4. 산출물 결정

**새 일상 파일 `DocuDog_threads.md`는 만들지 않음.**  
진입점은 이미 `DocuDog_status.md`(+html). 파일을 더 늘리면 “오늘 뭘 열지”가 다시 흔들림.

| 산출물 | 역할 |
|--------|------|
| **`DocuDog_status.md` + `.html` (주 화면)** | 최근 스레드 Top N. MD는 접힌 목록, HTML은 `<details>`로 메일처럼 펼침 |
| **`DocuDog_state.json`** | `threads[]` 스냅샷(기계용). MCP·HTML이 같이 읽음 |
| **`DocuDog_lineage.md`** | 보관. 그룹 전체 멤버·SHA. 스레드 ID만 나중에 교차 참조 |
| **`classification_report.md`** | 이벤트 로그 유지. 행에 thread 링크는 **2차** (선택) |
| **MCP** | `docudog_status`에 threads 요약 포함 + 이후 `docudog_threads` |

HTML 쌍은 report와 같이 status에도 이미 있음. 접힘 UI는 **HTML이 본진**, MD는 Cursor/메모장에서도 읽히는 짧은 트리.

모바일 digest는 스레드 헤더 3개만 (선택, 후순위).

---

## 5. 스레드 모델 (구현 계약)

`docudog/threads.py`가 분류/status 갱신 시 `state.threads`를 재계산 (전체 재생성, lineage와 동일).

```text
thread:
  id            # 안정 키: "ver:" + lineage_group_key  또는  "conv:" + 정규화 폴더
  kind          # version | conversation | mixed
  title         # 사람용 짧은 제목 (stem 또는 폴더명)
  latest_path
  last_utc
  member_count
  today_n       # 오늘 분류된 멤버 수 (안읽음 대체)
  max_security  # 멤버 중 최고 P
  members[]     # 시간순 오래된→최신 또는 최신→오래됨(설정)
    path, sha12, utc, summary, security_level, role
    role: latest | version | peer
```

**묶는 규칙 (1차, LLM 없음)**

- version: 기존 `_build_multi_groups` 결과 (filename_key + similarity). 멤버 ≥2.
- conversation: 같은 watch 하위 폴더에서, 최근 활동 기준 **서로 다른 lineage 키**가 2개 이상이고 context_bundle 또는 태그 교집합. 과병합 방지: 폴더 단위 상한(예: 멤버 12), 루트 Documents 통째 묶기 금지(깊이 ≥ 과제 폴더).
- mixed: version 그룹이 conversation에 포함되면 헤더는 폴더/주제, 펼침에 버전 서브리스트.

**헤더 정렬:** `last_utc` 내림차순 (메일함처럼 최근 대화가 위).

**한 줄 본문:** 최신 `summary` 또는 `last_change_summary`. 펼침 행은 basename + 시각 + 한 줄.

---

## 6. 구현 단계

### P0 — 받은편지함 섹션 (status)

- `threads.build_threads(state, config)` → `state["threads"]` (상위 N만 저장해도 됨, 기본 20).
- `status_dashboard`: 「권장 최신본」+「같이 볼 후보」를 **「최근 대화」로 통합**하거나 그 위에 두고, 구 섹션은 접거나 제거해 중복 축소.
- MD 예:

```markdown
## 최근 대화

- **Edge AI 기반 하이브리드 Agent AI 플랫폼** (9) · 민감 (P2) · 오늘 +3
  - 최신: `연구개발보고서 v1.md` — Edge AI와 sLLM 결합…
  - 이전: `브리프 v2 …docx` · `[컨셉]….pptx` · …
```

- HTML: `<details><summary>제목 (n) · 최신 파일</summary>…</details>`
- 상한: 헤더 8~12, 펼침 멤버 8. 나머지는 lineage 링크.

### P1 — MCP

- `docudog_status.digest`에 `threads_top[]` (id, title, latest, count, today_n).
- `docudog_thread(id | path)` 멤버 타임라인. PPT 참고 목록이 “검색 10건”이 아니라 “이 대화의 파일들”이 됨.

### P2 — 리포트 교차 (선택)

- classify 행에 짧은 thread title (append 호환). 본진은 아님.

설정 키 (초안): `thread_settings.enabled` (기본 true), `max_threads`, `max_members`, `include_conversations` (폴더 대화 on/off).

---

## 7. 리스크

- **과병합:** 유사도 클러스터가 이미 lineage에서 이슈. 대화 스레드는 **폴더 깊이**로 가둠. Documents 루트는 conversation 금지.
- **중복 UI:** 최신본 Top / related / 스레드가 같은 파일을 세 번 말함 → status에서 스레드가 이기게 정리.
- **P1이 스레드에 섞임:** 헤더에 `max_security` 표시. 본문 발췌는 기존 mcp_settings 유지.
- **재계산 비용:** 파일 수백이면 union-find는 기존 lineage와 동일 상한 (`max_files_for_similarity`).

---

## 8. 확인 시나리오

1. `제안서_v1.docx` / `제안서_최종.docx` → 버전 스레드 1개, 헤더는 최종.
2. Edge AI 과제 폴더의 pptx+docx+xlsx → 대화 스레드 1개 (폴더명 제목).
3. 무관한 Desktop 파일은 스레드 안 탐 (싱글톤).
4. 일상 확인은 `DocuDog_status.html`만 열고 펼침. lineage는 멤버 전부 필요할 때만.
