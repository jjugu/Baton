# Baton Python Architecture Spec

gorchera Go → baton Python 재구현의 타겟 아키텍처.

## 패키지 구조

```
baton/
├── pyproject.toml
├── baton/
│   ���── __init__.py              # __version__
│   ├── __main__.py              # python -m baton 엔트리포인트
│   ├── cli.py                   # Typer CLI
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── types.py             # Pydantic 모델: Job, Step, Chain, LeaderOutput, Enums
│   │   └── errors.py            # DomainError, ValidationError
│   ├── store/
│   │   ├── __init__.py
│   │   ├── state_store.py       # Job/Chain JSON 영속성 (atomic write)
│   │   └── artifact_store.py    # 아티팩트 파일 관리
│   ├── runtime/
│   │   ├── __init__.py
│   │   ├── runner.py            # asyncio subprocess 실행
│   │   └── lifecycle.py         # 프로세스 라이프사이클 (하네스 프로세스)
│   ├── provider/
│   │   ├── __init__.py
│   ���   ├── base.py              # Adapter Protocol + PhaseAdapter
│   │   ├── registry.py          # Registry + SessionManager
│   │   ├── protocol.py          # 프롬프트 빌더 + JSON 스키마
��   │   ├── codex.py             # Codex CLI 어댑터
│   │   ├── claude.py            # Claude CLI 어댑터
│   │   ├── mock.py              # Mock 어댑터 (테스트용)
│   ��   └── errors.py            # ProviderError + ErrorKind(12) + ErrorAction
│   ├── orchestrator/
│   │   ���── __init__.py
│   │   ��── service.py           # 코어 루프 + 잡 라이프사이클 + 체인 관리
│   │   ├── planning.py          # Planner phase + SprintContract
│   │   ├── evaluator.py         # 완료 평가 + 리포트 병합
│   │   ├── verification.py      # VerificationContract 관리
│   │   ├── automated_check.py   # grep, file_exists, file_unchanged, no_new_deps
│   │   ├── parallel.py          # 병렬 워커 fan-out (max 2)
│   │   ├── workspace.py         # 워크스페이스 검증 + git worktree
��   │   └── job_runtime.py       # 잡 리스 관리 (heartbeat, recovery)
│   ├── mcp/
│   │   ├── __init__.py
│   │   └── server.py            # MCP JSON-RPC 2.0 stdio 서버 (19 도구)
│   ├── api/
│   │   ├── __init__.py
│   │   ├── server.py            # FastAPI 앱 + 미들웨어
│   │   ├── routes.py            # HTTP 엔드포인트 핸들��
│   │   └── views.py             # 응답 DTO (Pydantic)
│   └── web/
│       ├── index.html
│       ├── app.js
│       └── style.css
└── tests/
    ├���─ __init__.py
    ├── conftest.py              # pytest fixtures
    ├── test_domain.py
    ├── test_store.py
    ├── test_runtime.py
    ├── test_provider.py
    ├─��� test_orchestrator.py
    ├── test_mcp.py
    └── test_api.py
```

## 의존성 그래프 (하위 → 상위)

```
domain.types (의존 없음)
domain.errors (의존 없음)
provider.errors (← domain)
provider.base (← domain)
store (← domain)
runtime (← domain)
provider.registry (← provider.base, provider.errors)
provider.codex/claude/mock (← provider.base, runtime)
provider.protocol (← domain)
orchestrator (← domain, store, runtime, provider)
mcp (← domain, orchestrator)
api (← domain, orchestrator, store)
cli (← orchestrator, mcp, api)
```

## 핵심 타입 매핑 (Go → Python)

| Go | Python |
|----|--------|
| `struct Job` | `class Job(BaseModel)` |
| `JobStatus` (string const) | `class JobStatus(str, Enum)` |
| `interface Adapter` | `class Adapter(Protocol)` |
| `map[string]RoleOverride` | `dict[str, RoleOverride]` |
| `context.Context` | `asyncio` 패턴 (CancelScope) |
| `sync.Mutex` | `asyncio.Lock` |
| `chan Event` | `asyncio.Queue[Event]` |
| `goroutine` | `asyncio.create_task()` |
| `os/exec.Cmd` | `asyncio.create_subprocess_exec()` |
| `embed.FS` | `importlib.resources` 또는 FastAPI StaticFiles |

## 상태 머신 (Go와 동일하게 유지)

```
starting → planning → waiting_leader → waiting_worker → running → (loop)
                                      → complete → [evaluateCompletion] → done
                                      → fail → failed
                                      → blocked → blocked
max_steps_exceeded → blocked
```

터미널 상태: `done`, `failed`, `blocked`

## 환경 변수 (Go와 동일)

| 변수 | 용도 |
|------|------|
| `ANTHROPIC_API_KEY` | Claude CLI |
| `OPENAI_API_KEY` | Codex CLI |
| `OPENAI_ORG_ID` | Codex (optional) |
| `BATON_CLAUDE_BIN` | Claude CLI 경로 오버라이드 |
| `BATON_CODEX_BIN` | Codex CLI 경로 오버라이드 |
| `BATON_AUTH_TOKEN` | HTTP API 인증 토큰 |

## pyproject.toml 핵심 의존성

```toml
[project]
name = "baton"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "pydantic>=2.0",
    "fastapi>=0.110",
    "uvicorn[standard]>=0.30",
    "typer>=0.12",
    "sse-starlette>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",
]

[project.scripts]
baton = "baton.cli:app"
```
