---
name: baton-orchestrator
description: "Baton 프로젝트 빌드 오케스트레이터. gorchera(Go)를 Python으로 재구현하는 에이전트 팀을 조율한다. 'baton 빌드', 'baton 구현', 'Python 재구현', '오케스트레이터 개발' 등의 요청 시 반드시 이 스킬을 사용할 것."
---

# Baton Build Orchestrator

gorchera(Go 24K LOC)를 Python으로 재구현하는 에이전트 팀을 조율하는 오케스트레이터.

## 실행 모드: 에이전트 팀

## 에이전트 구성

| 팀원 | 에이전트 타입 | 역할 | 출력 |
|------|-------------|------|------|
| core-dev | core-dev (custom) | 도메인, 저장소, 오케스트레이터, provider | baton/ 코어 모듈 |
| interface-dev | interface-dev (custom) | MCP, HTTP API, CLI, 웹 | baton/ 인터페이스 모듈 |
| qa-inspector | general-purpose | 통합 검증, 테스트 | tests/ + QA 리포트 |

## 참조

- Go 원본: `C:/Claude/kmOffice/gorchera/`
- Python 아키텍처 스펙: `references/architecture-spec.md` — 필요 시 Read
- Go→Python 매핑: `references/go-python-mapping.md` — 필요 시 Read

## 워크플로우

### Phase 1: 준비 (리더)

1. `C:/Claude/kmOffice/baton/_workspace/` 생성
2. 프로젝트 기본 구조 생성:
   - `pyproject.toml` (의존성: pydantic, fastapi, uvicorn, typer, mcp)
   - `baton/__init__.py` (버전 정보)
   - 각 하위 패키지의 `__init__.py`
3. Go 원본의 핵심 인터페이스를 분석하여 구현 계획 수립

### Phase 2: 팀 구성

```
TeamCreate(
  team_name: "baton-build",
  members: [
    {
      name: "core-dev",
      agent_type: "core-dev",
      model: "opus",
      prompt: "Baton 코어 엔진을 구현하라. Go 원본: C:/Claude/kmOffice/gorchera/internal/. Python 타겟: C:/Claude/kmOffice/baton/baton/. Phase A(Foundation)부터 시작: domain/types.py, domain/errors.py, provider/errors.py, provider/base.py, store/, runtime/. 완성 후 Phase B(Core): provider 어댑터들, orchestrator/. 각 모듈 완성 시 qa-inspector에게 알리고 interface-dev에게 인터페이스 정보를 공유하라."
    },
    {
      name: "interface-dev",
      agent_type: "interface-dev",
      model: "opus",
      prompt: "Baton 인터페이스를 구현하라. Go 원본: C:/Claude/kmOffice/gorchera/. Python 타겟: C:/Claude/kmOffice/baton/baton/. core-dev가 도메인 모델을 완성하면 알림이 올 것이다. 그 전에 Go 원본의 MCP 도구 정의(internal/mcp/)와 API 라우트(internal/api/)를 분석하여 구조를 설계하라. core-dev 모델 완성 후 즉시 구현 시작. 각 모듈 완성 시 qa-inspector에게 알려라."
    },
    {
      name: "qa-inspector",
      agent_type: "qa-inspector",
      model: "opus",
      prompt: "Baton QA 검증을 수행하라. Go 원본: C:/Claude/kmOffice/gorchera/. Python 구현: C:/Claude/kmOffice/baton/baton/. core-dev와 interface-dev가 모듈 완성 시 알림을 보낼 것이다. 각 알림마다 Go 원본과 Python 구현을 교차 비교하여 검증하라. 버그 발견 시 해당 에이전트에게 즉시 수정 요청을 보내라. 검증 리포트는 _workspace/qa/에 저장하라. tests/ 디렉토리에 pytest 테스트도 작성하라."
    }
  ]
)
```

### Phase 3: Foundation 구현 (core-dev 주도)

**core-dev 작업 (Phase A - Foundation):**

```
TaskCreate(tasks: [
  {
    title: "도메인 모델 구현",
    description: "baton/domain/types.py — Job, Step, Chain, LeaderOutput, 모든 Enum을 Pydantic 모델로. Go: internal/domain/types.go",
    assignee: "core-dev"
  },
  {
    title: "에러 타입 구현",
    description: "baton/domain/errors.py + baton/provider/errors.py — ProviderError, ErrorKind(12종), ErrorAction. Go: internal/provider/errors.go",
    assignee: "core-dev"
  },
  {
    title: "Provider 인터페이스 정의",
    description: "baton/provider/base.py — Adapter Protocol (RunLeader, RunWorker, RunPlanner, RunEvaluator). Go: internal/provider/provider.go",
    assignee: "core-dev"
  },
  {
    title: "상태 저장소 구현",
    description: "baton/store/ — StateStore(atomic JSON), ArtifactStore. Go: internal/store/",
    assignee: "core-dev"
  },
  {
    title: "런타임 구현",
    description: "baton/runtime/ — subprocess runner, 프로세스 라이프사이클. Go: internal/runtime/",
    assignee: "core-dev"
  }
])
```

**interface-dev 병렬 작업 (Go 분석 + 프레임워크 준비):**

```
TaskCreate(tasks: [
  {
    title: "MCP 도구 스키마 분석",
    description: "Go internal/mcp/server.go에서 19개 도구의 이름, 파라미터, 반환 타입을 추출하여 _workspace/mcp_schema.md에 정리",
    assignee: "interface-dev"
  },
  {
    title: "API 엔드포인트 분석",
    description: "Go internal/api/server.go에서 모든 HTTP 엔드포인트, 요청/응답 구조를 추출하여 _workspace/api_schema.md에 정리",
    assignee: "interface-dev"
  },
  {
    title: "CLI 서브커맨드 분석",
    description: "Go cmd/gorchera/main.go에서 모든 CLI 커맨드, 플래그를 추출하여 _workspace/cli_schema.md에 정리",
    assignee: "interface-dev"
  }
])
```

**리더 모니터링:**
- core-dev의 도메인 모델 완성을 확인 (TaskGet)
- 완성 시 interface-dev에게 구현 시작 안내

### Phase 4: Core + Interface 병렬 구현

**core-dev 작업 (Phase B - Core):**

```
TaskCreate(tasks: [
  {
    title: "Provider 어댑터 구현",
    description: "baton/provider/ — codex.py, claude.py, mock.py, registry.py, protocol.py. Go: internal/provider/",
    assignee: "core-dev"
  },
  {
    title: "오케스트레이터 코어 루프",
    description: "baton/orchestrator/service.py — runLoop, 상태 전이, 잡 라이프사이클. Go: internal/orchestrator/service.go",
    assignee: "core-dev"
  },
  {
    title: "플래닝 + 평가",
    description: "baton/orchestrator/planning.py, evaluator.py, verification.py, automated_check.py. Go: internal/orchestrator/",
    assignee: "core-dev"
  },
  {
    title: "워크스페이스 + 잡 런타임",
    description: "baton/orchestrator/workspace.py, job_runtime.py, parallel.py. Go: internal/orchestrator/",
    assignee: "core-dev"
  }
])
```

**interface-dev 작업 (Phase B - Interfaces):**

```
TaskCreate(tasks: [
  {
    title: "MCP 서버 구현",
    description: "baton/mcp/server.py — 19개 도구, JSON-RPC 2.0, 알림. core-dev의 도메인 모델을 import. Go: internal/mcp/",
    assignee: "interface-dev"
  },
  {
    title: "HTTP API 구현",
    description: "baton/api/ — FastAPI 서버, 모든 라우트, SSE, 인증. Go: internal/api/",
    assignee: "interface-dev"
  },
  {
    title: "CLI 구현",
    description: "baton/cli.py + baton/__main__.py — Typer 기반 모든 서브커맨드. Go: cmd/gorchera/",
    assignee: "interface-dev"
  },
  {
    title: "웹 대시보드",
    description: "baton/web/ — gorchera/web/에서 복사 후 'gorchera'→'baton' 브랜딩 수정, FastAPI static mount",
    assignee: "interface-dev"
  }
])
```

**qa-inspector — 점진적 QA:**
- 각 모듈 완성 알림마다 즉시 Go-Python 교차 검증
- 검증 리포트: `_workspace/qa/{module}_report.md`
- 버그 발견 시 해당 에이전트에게 즉시 수정 요청

### Phase 5: 통합 + 최종 검증

1. 리더가 모든 TaskGet으로 완료 확인
2. qa-inspector에게 최종 통합 검증 요청:
   - 전체 import 그래프 검증 (순환 의존 없음)
   - MCP 19개 도구 vs Go 원본 1:1 대조
   - API 엔드포인트 vs Go 원본 1:1 대조
   - 상태 머신 전이 완전성
3. 리더가 빌드 테스트: `cd C:/Claude/kmOffice/baton && pip install -e . && python -m baton --help`
4. CLAUDE.md 생성

### Phase 6: 정리

1. 팀원들에게 종료 요청 (SendMessage)
2. TeamDelete로 팀 정리
3. `_workspace/` 보존
4. 사용자에게 결과 요약 보고:
   - 생성된 파일 목록
   - 구현된 기능 목록
   - 미구현/알려진 이슈
   - 실행 방법

## 데이터 흐름

```
[리더: 프로젝트 구조 생성]
       ↓
[core-dev: Foundation] ←─SendMessage─→ [qa-inspector: 점진적 QA]
       ↓ (도메인 모델 완성 알림)
[core-dev: Core] ←──────────────→ [interface-dev: Interfaces]
       ↓                                    ↓
       └──── SendMessage → [qa-inspector] ←─┘
                                ↓
                    [리더: 최종 통합 + 빌드 테스트]
```

## 에러 핸들링

| 상황 | 전략 |
|------|------|
| 팀원 1명 중지 | SendMessage로 상태 확인 → 재시작 또는 다른 팀원에게 작업 재할당 |
| core-dev 지연 | interface-dev는 Go 분석 작업 계속 진행, stub import로 구현 시작 |
| Go-Python 매핑 불가 | core-dev가 Python 관용구로 대안 설계, qa-inspector가 동작 동등성 검증 |
| 빌드 실패 | qa-inspector가 import 그래프 분석, 순환 의존 해소 |
| 테스트 실패 | 실패 원인 분석 후 해당 팀원에게 수정 요청 |

## 테스트 시나리오

### 정상 흐름
1. 리더가 프로젝트 구조 생성
2. Phase 2에서 3명 팀 구성
3. Phase 3에서 Foundation 구현 (core-dev) + Go 분석 (interface-dev)
4. Phase 4에서 Core + Interface 병렬 구현, qa-inspector 점진적 검증
5. Phase 5에서 통합 빌드 성공
6. 예상: `baton/` 패키지가 설치 가능하고 `python -m baton --help` 실행됨

### 에러 흐름
1. Phase 4에서 qa-inspector가 MCP 도구 파라미터 불일치 발견
2. interface-dev에게 수정 요청 SendMessage
3. interface-dev가 수정 후 qa-inspector에게 재검증 요청
4. 재검증 통과 → Phase 5 진행
5. 최종 보고서에 "MCP 스키마 수정 1건" 기록
