# DocuDog

Windows 로컬 PC에서 문서를 조용히 감시하고, **유휴(idle) 시간**에 온디바이스 LLM으로 태그·보안 등급·요약을 부여한 뒤, Markdown 리포트와 lineage 맵을 로컬에만 쌓는 **Stage 1 (Watcher)** MVP입니다.

> **철학:** 사람은 자연스럽게(때로는 무질서하게) 일하고, 정리는 AI가 뒤에서 한다.  
> 장기 비전은 [master-plan.md](master-plan.md)를 참고하세요. 현재 코드는 **UI·중앙 서버 동기화·DLP 차단** 없이 watcher 파이프라인만 구현합니다.

## 목표

- 지정 폴더의 문서 생성·수정을 백그라운드에서 수집
- 사용자 입력이 **일정 시간 유휴**일 때만 처리해 CPU/GPU 부하를 줄임
- 로컬 LLM으로 **태그**, **보안 등급(P1–P4)**, **요약** 생성
- `classification_report.md`, `DocuDog_state.json`, (옵션) 감사·lineage Markdown을 **로컬에만** 기록
- 원본·추론 과정을 클라우드로 보내지 않는 **로컬 프라이버시** 거버넌스 검증

## 현재 구현 범위 (Stage 1)

| 영역 | 설명 |
|------|------|
| 감시 | `watchdog` + Windows `GetLastInputInfo` 유휴 감지 |
| 라우팅 | 확장자·크기 필터, SHA-256 중복 스킵, txt/md/docx/pptx/xlsx 텍스트 추출 |
| 분류 | LiteRT-LM, LM Studio(OpenAI 호환 HTTP), 또는 mock |
| 산출물 | 분류 리포트, state JSON, P1/P2 감사 로그, 문서 lineage(Mermaid) |
| 미구현 | 웹 UI, 서버 RAG, PDF/HWP 본문 추출, 커널/이메일 DLP |

상세 기능 목록: [docs/implemented-features.md](docs/implemented-features.md) · 아키텍처: [ARCHITECTURE.md](ARCHITECTURE.md)

## 요구 사항

- **OS:** Windows 10/11 (유휴 감지·백그라운드 우선순위는 Windows 기준)
- **Python:** 3.10+ 권장
- **LLM (택 1):**
  - [LiteRT-LM](https://github.com/google-ai-edge/LiteRT-LM) + `.litertlm` 번들, 또는
  - [LM Studio](https://lmstudio.ai/) 등 OpenAI 호환 `/v1/chat/completions` 서버, 또는
  - `use_mock: true`로 파이프라인만 검증

## 빠른 시작

### 1. 클론 및 의존성

```powershell
git clone https://github.com/dasvayda/DocuDog.git
cd DocuDog
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install PyYAML   # config.yml 오버레이 사용 시
```

### 2. 설정

```powershell
copy config.example.json config.json
# 선택: config.example.yml 을 config.yml 로 복사해 model 등만 덮어쓰기
```

`config.json`에서 최소한 다음을 맞춥니다.

- `watch_settings.target_directories` — 감시할 폴더
- `paths.state_path`, `paths.report_path` — state·리포트 저장 위치
- `model.*` — 추론 백엔드 (아래 **모델 백엔드** 참고)

### 3. (선택) LiteRT 모델 다운로드

Gemma LiteRT 번들은 Hugging Face 게이트 리포지터리입니다. 라이선스 동의 후:

```powershell
pip install -U "huggingface_hub[cli]"
hf auth login
python tools/download_litert_gemma.py
```

출력된 `*.litertlm` 경로를 `config.json`의 `model.litert_lm_bundle_path`에 넣습니다.

### 4. 실행

저장소 **루트**에서 실행합니다 (`config.json`이 현재 디렉터리 기준으로 로드됩니다).

**첫 분류 스모크 (유휴·워처 없음):**

```powershell
python tools/classify_one.py fixtures\sample_internal_memo.md
# 또는
python main.py --file fixtures\sample_internal_memo.md
```

**백그라운드 데몬:**

```powershell
python main.py
```

**큐에서 한 건만 처리 후 종료:**

```powershell
python main.py --once
# 또는
$env:DOCUDOG_RUN_ONCE = "1"; python main.py
```

**회귀 스모크 (mock, LLM 불필요):**

```powershell
python tools/regression_smoke.py
```

- 단일 인스턴스: 같은 `main.py`가 이미 떠 있으면 이전 프로세스를 종료하고 재시작합니다 (`--file` 모드는 run lock 없음).
- 유휴 대기: `idle_settings.idle_trigger_seconds`(기본 60초) 또는 환경변수 `DOCUDOG_IDLE_TRIGGER_SECONDS`
- 테스트용 즉시 처리: `idle_settings.skip_idle_wait_for_testing: true`

### 5. 결과 확인

기본 경로(설정에 따라 다름):

| 파일 | 내용 |
|------|------|
| `classification_report.md` | 파일별 태그·등급·요약 |
| `DocuDog_state.json` | 해시·메타, 마지막 추론 백엔드 |
| `DocuDog_audit_log.md` | P1/P2 분류 시 감사 행 |
| `DocuDog_lineage.md` | 파일명·유사도 기반 lineage(Mermaid) |

## 모델 백엔드

`config.json` / `config.yml`의 `model` 블록:

| 설정 | 동작 |
|------|------|
| `enable_lm_studio: true` | LM Studio 등 HTTP 백엔드 (`model.lm_studio`) |
| `enable_litert_lm: true` | 로컬 `.litertlm` 번들 |
| 둘 다 `true` | `inference_preference`: `lm_studio` 또는 `litert_lm` |
| 둘 다 `false` | mock 분류 (`inference_backends_disabled`) |
| `use_mock: true` | 항상 mock |

**LM Studio 예시** (`config.example.yml` 참고):

```yaml
model:
  enable_litert_lm: false
  enable_lm_studio: true
  lm_studio:
    base_url: "http://127.0.0.1:1234"
    model: "<lm-studio-model-id>"
    timeout_seconds: 120
```

**LiteRT 주의:** 일부 번들은 prefill 토큰 상한이 작습니다. `Input token ids are too long` 오류 시 `litert_classify_context_cap`, `litert_aux_max_user_chars`를 낮추세요. IDE에서 RAM 부족 시 `startup_probe: false`로 시작 시 번들 로드를 건너뜁니다.

## 유용한 환경 변수

| 변수 | 설명 |
|------|------|
| `DOCUDOG_DEBUG=1` | Python DEBUG 로그 |
| `DOCUDOG_IDLE_TRIGGER_SECONDS` | 유휴 트리거(초) |
| `DOCUDOG_SKIP_MODEL_PROBE=1` | HTTP `GET /v1/models` 시작 프로브 생략 |
| `DOCUDOG_FORCE_STARTUP_PROBE=1` | LiteRT 시작 프로브 강제 |
| `DOCUDOG_VERBOSE_INFERENCE=1` | 추론 실패 시 traceback |

## 프로젝트 구조

```
DocuDog/
  main.py              # 진입점 (오케스트레이션)
  config.json          # 로컬 설정 (git 제외, example 복사)
  docudog/
    watcher.py         # 파일 감시·유휴
    router.py          # 필터·추출·분류 호출
    inference.py       # LiteRT / HTTP / mock
    reporter.py        # Markdown 리포트
    lineage.py         # DNA 맵·클러스터링
    audit.py           # P1/P2 감사 로그
  tools/               # 모델 다운로드, 벤치, 태그 동기화 등
  docs/                # 기능 목록, 태그 오버라이드 가이드
```

## 태그·등급 수동 재지정

웹 UI 없이 `DocuDog_tag_overrides.json`을 편집합니다. 예시: [DocuDog_tag_overrides.example.json](DocuDog_tag_overrides.example.json) · 가이드: [docs/owner-tag-overrides.md](docs/owner-tag-overrides.md)

## 로드맵 (미구현)

Shadow Git, 벡터 DB, 서버 지식 그래프, 파일 시스템 필터 드라이버, LoRA 미세조정 등은 [master-plan.md](master-plan.md)의 장기 계획입니다.

## 라이선스

저장소 루트에 `LICENSE`가 없으면 사용 전 저장소 소유자에게 문의하세요. LiteRT/Gemma 등 **모델 가중치**는 각 배포처(Hugging Face, Google 등)의 라이선스를 따릅니다.

## 관련 링크

- GitHub: https://github.com/dasvayda/DocuDog
- [LiteRT-LM](https://github.com/google-ai-edge/LiteRT-LM)
- [AGENTS.md](AGENTS.md) — AI 코딩 에이전트용 요약
