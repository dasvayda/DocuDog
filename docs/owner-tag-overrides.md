# 소유자 태그·보안등급 재지정 (Owner overrides)

DocuDog MVP에는 **웹페이지(UI)가 없습니다.** 소유자(로컬 PC 사용자)가 모델 결과를 바로잡는 방식은 **로컬 JSON 파일 편집**과, 필요 시 **동기화 스크립트**입니다.

## 무엇을 하는 기능인가

- 분류 직후 **`DocuDog_tag_overrides.json`**에 해당 파일 경로가 있으면, 그 안의 **`tags`** / **`security_level`**이 **모델 출력보다 우선**합니다.
- 리포트(`classification_report.md`)와 상태(`DocuDog_state.json`)에는 **적용된 값**이 들어가고, Inference 열에 **`+ owner tags`**처럼 표시됩니다.
- 모델이 다시 준 값은 state에 **`model_tags`**, **`model_security_level`**로 남습니다.

## 파일 위치 (재지정 경로)

| 설정 | 의미 |
|------|------|
| `paths.tag_overrides_path` 비움 | **`DocuDog_state.json`과 같은 폴더**에 `DocuDog_tag_overrides.json` 사용 |
| `paths.tag_overrides_path` 지정 | 그 경로(환경변수 `%USERPROFILE%` 등 확장 가능)를 사용 |

저장소 루트의 **[DocuDog_tag_overrides.example.json](../DocuDog_tag_overrides.example.json)** 을 복사해 이름만 바꾸고 편집해도 됩니다.

## JSON 형식

- 최상위: `"version": 1`, `"entries": { ... }`
- **`entries`의 키**: 분석 대상 파일의 **절대 경로**, 백슬래시 그대로 써도 됨(예: Windows). DocuDog은 내부적으로 경로를 정규화해 매칭합니다.
- **`entries`의 값**:
  - `tags`: 문자열 배열(필수는 아님; 비우면 태그는 모델 값 유지)
  - `security_level`: `P1`~`P4` 중 하나(선택; 유효하지 않으면 무시)

한 항목에서 **태그만** 또는 **등급만** 바꿀 수 있습니다.

## 언제 반영되나

1. **다음에 그 파일이 다시 분석될 때**  
   내용 해시가 바뀌어 LLM이 다시 돌면, 그 결과에 override가 곧바로 합쳐집니다.

2. **내용은 그대로인데 JSON만 고친 경우**  
   자동 감시는 override 파일을 다시 읽지 않습니다. 아래 중 하나를 하세요.
   - `python tools/sync_tag_overrides.py` 실행 — state·계보(`DocuDog_lineage.md`)만 override 기준으로 맞춤 (**리포트 과거 행은 수정하지 않음**).
   - 또는 해당 파일을 한 번 저장·편집해 해시가 바뀌게 하면 전체 파이프라인이 다시 돌면서 override가 적용됩니다.

## 웹페이지가 아닌 이유 (MVP 범위)

[master-plan.md](../master-plan.md) Stage 1은 **로컬 데몬 + 마크다운 출력**만 전제합니다. 브라우저 서버·인증·실시간 편집 UI는 범위 밖이며, 나중에 붙일 수 있도록 **데이터만 JSON으로 노출**해 둔 것입니다.

## 관련 코드

- `owner_tags.py` — 로드·병합
- `router.py` (`docudog/router.py`) — 분류 후 병합, state 필드 작성
- `tools/sync_tag_overrides.py` — 재추론 없이 state/lineage만 동기화
