# Cursor / DocuDog 메모리 점검 목록

다른 PC(노트북)에서 **Cursor Agent 앱 RAM이 비정상적으로 커질 때** 쓰는 체크리스트임.  
목적은 “DocuDog·Zvec·로컬 LLM이 원인인지”를 **설정 차이까지 포함해** 빠르게 가르는 것.

관련: [mcp-connect.md](mcp-connect.md) · [AGENTS.md](../AGENTS.md) · `config.example.json`의 `semantic_search` / `model`

---

## 0. 먼저 알아둘 것

| 오해 | 실제 |
|------|------|
| Agent **목록에만** 있어도 Zvec/LLM이 RAM을 먹는다 | **거의 아님.** 목록은 채팅 기록. 워크스페이스를 열거나 MCP/분류가 돌아가야 큼 |
| 레포에 Zvec 코드가 있으면 항상 로드된다 | **아님.** `semantic_search.enabled: true` + 색인/검색 시에만 임베딩·Zvec 로드 |
| 두 PC 설정이 같다 | **다를 수 있음.** `config.json`은 gitignore라 **기기마다 로컬 파일** |

**노트북마다 달라질 수 있는 것 (우선 확인):**

1. `%USERPROFILE%` 아래 로컬 `config.json` (레포 루트, git에 없음)
2. Cursor **프로젝트** `.cursor/mcp.json` vs 사용자 `%USERPROFILE%\.cursor\mcp.json`
3. MCP **docudog** Enabled 여부 (프로젝트 서버는 기본 off인 경우 많음)
4. `semantic_search.enabled` / embedding 모델 / `requirements-semantic.txt` 설치 여부
5. `model.backend` = `litert_lm` + 번들 경로 (수 GB)
6. 레포 안·옆의 `models/`, `*.litertlm`, `*.gguf`, Hugging Face 캐시
7. DocuDog `main.py` / 트레이가 백그라운드 실행 중인지
8. Cursor가 연 **폴더 범위** (레포만 vs `AI-Coding-Space` 전체)

---

## 1. 증상 기록 (1분)

점검 전에 적어 두면 비교가 쉬움.

- [ ] Cursor Agent 총 작업 세트(대략): _____ GB
- [ ] DocuDog 폴더를 **연 상태**인가 / **안 연 상태**인가
- [ ] 문제 에이전트 채팅을 **연 상태**인가 / 목록에만 있는가
- [ ] 최근 Zvec·MCP·LiteRT를 켠 적이 있는가 (대략 날짜)

**분리 테스트 (가장 중요):**

1. Cursor 완전 종료 → 작업 관리자에서 `Cursor.exe` 없는지 확인  
2. DocuDog **없이** Cursor만 실행 → RAM 기록  
3. DocuDog 워크스페이스만 열기 (Agent 채팅 안 염) → RAM  
4. 해당 Agent 채팅 열기 → RAM  
5. Settings → MCP에서 **docudog Disabled** 후 재시작 → RAM  

어디서 뛰는지에 따라 원인이 갈림.

---

## 2. DocuDog 로컬 설정 (노트북 A vs B 차이 핵심)

레포 루트에서 (PowerShell):

```powershell
cd <DocuDog-클론-경로>
python -c "import json; d=json.load(open('config.json',encoding='utf-8')); m=d.get('model') or {}; ss=d.get('semantic_search') or {}; print('backend', m.get('backend')); print('enable_litert', m.get('enable_litert_lm')); print('enable_lm_studio', m.get('enable_lm_studio')); print('use_mock', m.get('use_mock')); print('bundle', m.get('litert_lm_bundle_path')); print('startup_probe', m.get('startup_probe')); print('semantic_search', ss)"
```

체크:

- [ ] `config.json`이 **존재하는가** (없으면 example만 보고 착각하기 쉬움)
- [ ] `semantic_search.enabled` → **true면 RAM 후보 1순위**
- [ ] `embedding_model` / `embedding_device` (cpu면 RAM, cuda면 VRAM+RAM)
- [ ] `model`이 `litert_lm`이고 `litert_lm_bundle_path`가 채워져 있는가
- [ ] `startup_probe: true` + LiteRT면 **시작 시 번들 로드** 가능 (기본은 false 권장)

`semantic_search` 키가 없거나 `{}`이면 코드상 **기본 off**.

---

## 3. Zvec / 임베딩이 실제로 켜져 있는지

```powershell
# 산출물 홈 (기본)
$docHome = Join-Path $env:USERPROFILE '.docudog'
Test-Path $docHome
if (Test-Path $docHome) {
  Get-ChildItem $docHome -Force
  $si = Join-Path $docHome 'semantic_index'
  if (Test-Path $si) {
    $bytes = (Get-ChildItem $si -Recurse -File -EA SilentlyContinue | Measure-Object Length -Sum).Sum
    "semantic_index MB = $([math]::Round($bytes/1MB,1))"
  }
}

# 선택 패키지 설치 여부
python -c "import importlib.util as u; print('zvec', bool(u.find_spec('zvec'))); print('sentence_transformers', bool(u.find_spec('sentence_transformers')))"
```

체크:

- [ ] `%USERPROFILE%\.docudog\semantic_index` (또는 config의 `index_path`)가 **존재하는가**
- [ ] `zvec` / `sentence_transformers`가 **설치**되어 있는가 (`requirements-semantic.txt`)
- [ ] HF 캐시가 큰가: `%USERPROFILE%\.cache\huggingface` (임베딩 모델 다운로드본)

**부하가 큰 순간:**

- `python tools/rebuild_semantic_index.py`
- 분류 직후 인덱스 upsert (`enabled`일 때)
- MCP 도구 `docudog_semantic_search`

코드는 기본적으로 Zvec를 **lazy import**함. enabled가 아니면 인덱싱만으로 모델을 올리지 않음.

임시 완화:

```json
"semantic_search": { "enabled": false }
```

그다음 Cursor·DocuDog MCP·`main.py` 재시작.

---

## 4. MCP (Agent 목록과 별개 — 여기가 자주 헷갈림)

| 위치 | 역할 |
|------|------|
| 프로젝트 `.cursor/mcp.json` | 이 레포를 열 때 DocuDog MCP |
| `%USERPROFILE%\.cursor\mcp.json` | 전역 MCP (다른 프로젝트에서도) |

```powershell
# 프로젝트 / 사용자 MCP에 docudog가 있는지
Select-String -Path ".\.cursor\mcp.json","$env:USERPROFILE\.cursor\mcp.json" -Pattern "docudog" -EA SilentlyContinue

# DocuDog MCP python이 떠 있는지
Get-CimInstance Win32_Process -Filter "name='python.exe'" -EA SilentlyContinue |
  Where-Object { $_.CommandLine -match 'docudog_mcp' } |
  Select-Object ProcessId, @{N='MB';E={[math]::Round($_.WorkingSetSize/1MB,0)}}, CommandLine
```

체크:

- [ ] Cursor **Settings → MCP**에서 `docudog`가 **Enabled**인가
- [ ] `docudog_mcp.py` 프로세스가 **상주**하는가 → 상주면 MCP 연결 중 (Zvec off여도 기본 Python MCP RAM은 씀; 보통 가중치급은 아님)
- [ ] `docudog_semantic_search`를 에이전트가 **자주 호출**하는가 (호출 시 임베딩 로드)

완화: MCP에서 docudog **Disabled** → Cursor 재시작 → RAM 비교.

---

## 5. 로컬 LiteRT / 거대 가중치 (Zvec와 별트랙)

```powershell
# 레포 안 가중치 (있으면 Cursor 인덱싱·감시 위험)
Test-Path .\models
Get-ChildItem -Recurse -Include *.litertlm,*.gguf,*.safetensors -Depth 4 -EA SilentlyContinue |
  Select-Object -First 20 FullName, @{N='GB';E={[math]::Round($_.Length/1GB,2)}}

# .cursorignore / watcher 제외가 있는지
Test-Path .\.cursorignore
Select-String -Path .\.cursorignore,.vscode\settings.json -Pattern "litertlm|models|gguf" -EA SilentlyContinue
```

체크:

- [ ] 번들이 **워크스페이스 안**에 있는가 → `.cursorignore`에 `models/`, `*.litertlm` 등이 있어야 함
- [ ] Cursor가 **상위 폴더**(가중치 포함)를 루트로 열지 않았는가
- [ ] `main.py` / 트레이가 LiteRT로 돌며 RAM을 먹는가 (작업 관리자에서 `python` + `main.py` 확인)

권장: 가중치는 레포 **밖**, `litert_lm_bundle_path`만 절대 경로. `startup_probe`는 평소 **false**.

---

## 6. Cursor Agent 쪽 (DocuDog 코드와 무관한 부하)

- [ ] 긴 Agent 채팅을 여러 개 **동시에** 열어 두지 않았는가
- [ ] 같은 노트북에서 Unity MCP 등 **다른 MCP**가 여러 python을 띄우는가
- [ ] Cursor 버전 / Agent 앱 버전이 다른 PC와 다른가
- [ ] 「Agent 목록에만 있음」vs「그 채팅을 연 채 방치」를 구분했는가  
  → **연 채팅 + 워크스페이스 + MCP** 조합이 RAM을 씀. 목록 행 자체는 아님.

---

## 7. DocuDog 데몬 / 트레이

```powershell
Get-CimInstance Win32_Process -Filter "name='python.exe'" -EA SilentlyContinue |
  Where-Object { $_.CommandLine -match 'docudog|main\.py' } |
  Select-Object ProcessId, @{N='MB';E={[math]::Round($_.WorkingSetSize/1MB,0)}}, CommandLine
```

체크:

- [ ] 백그라운드 watcher가 돌아가는가
- [ ] 유휴마다 분류 + (enabled 시) 시맨틱 upsert가 반복되는가
- [ ] 감시 루트가 Desktop/Downloads/Documents 전체로 넓어 큐가 계속 도는가

완화 시험: 트레이/`main.py` 종료 후 Cursor만 두고 RAM 재측정.

---

## 8. 판정 가이드

| 관찰 | 유력 원인 |
|------|-----------|
| DocuDog 폴더 안 열면 RAM 정상 | 워크스페이스 인덱싱·프로젝트 MCP·설정 |
| MCP docudog off면 크게 감소 | MCP 상주 또는 semantic 도구 호출 |
| `semantic_search.enabled` true + 인덱스/패키지 있음 | Zvec + sentence-transformers |
| LiteRT 번들 경로 + python main 큼 | 로컬 LLM 추론 프로세스 |
| Agent 목록만, 워크스페이스·MCP 없음인데도 큼 | Cursor/Agent 앱 자체 또는 다른 MCP·확장 |

---

## 9. 다른 노트북에 복사해 실행할 최소 명령 묶음

DocuDog 클론 루트에서:

```powershell
Write-Host "=== config snapshot ==="
if (Test-Path .\config.json) {
  python -c "import json;d=json.load(open('config.json',encoding='utf-8'));print('model',{k:d.get('model',{}).get(k) for k in ['backend','enable_litert_lm','enable_lm_studio','use_mock','litert_lm_bundle_path','startup_probe']});print('semantic_search',d.get('semantic_search'))"
} else { Write-Host "no config.json" }

Write-Host "=== semantic pkgs / index ==="
python -c "import importlib.util as u;print('zvec',bool(u.find_spec('zvec')));print('st',bool(u.find_spec('sentence_transformers')))"
$si = Join-Path $env:USERPROFILE '.docudog\semantic_index'
Write-Host "index_exists=$([bool](Test-Path $si))"

Write-Host "=== processes ==="
Get-CimInstance Win32_Process -Filter "name='python.exe'" -EA SilentlyContinue |
  Where-Object { $_.CommandLine -match 'docudog|docudog_mcp|main\.py' } |
  ForEach-Object { "{0} MB={1:N0} {2}" -f $_.ProcessId, ($_.WorkingSetSize/1MB), $_.CommandLine }

Write-Host "=== weights in repo ==="
@(Get-ChildItem -Recurse -Include *.litertlm,*.gguf -Depth 3 -EA SilentlyContinue | Measure-Object).Count
```

결과를 메모장에 붙여 두면 PC 간 비교가 됨.

---

## 10. 문서 이력

| 날짜 | 요약 |
|------|------|
| 2026-09-12 | 초안: 노트북 간 config/MCP/Zvec/LiteRT/Agent 목록 혼동 점검용 |
