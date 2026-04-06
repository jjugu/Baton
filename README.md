[한국어](#baton-ko) | [English](#baton-en)

---

<a id="baton-ko"></a>

# Baton

Python asyncio 기반 멀티 에이전트 오케스트레이션 엔진.

```
Director (계획) -> Leader (지시) -> Executor (구현) -> Evaluator (검증 게이트)
```

Evaluator 게이트는 절대 우회할 수 없습니다 -- `done` 상태는 반드시 evaluator 승인을 통과해야 도달합니다.

## 주요 기능

- **3-agent 파이프라인** -- 엄격한 evaluator 게이트
- **3개 프로바이더** -- Claude (Anthropic), Codex (OpenAI), Mock (테스트용)
- **역할별 모델 설정** -- opus(추론), sonnet(실행) 등 자유 배정
- **Job 체인** -- 순차적 다단계 워크플로우
- **워크스페이스 격리** -- git worktree를 통한 작업 분리
- **MCP 서버** -- Claude Code 직접 통합
- **HTTP API** -- SSE 이벤트 스트리밍 + 웹 대시보드
- **토큰 사용량 추적** -- 실시간 비용 모니터링
- **CLI** -- 22개 서브커맨드
- **한국어/영어 대시보드** -- 언어 전환 지원

## 설치

```bash
# GitHub에서 설치
pip install git+https://github.com/jjugu/Baton.git

# 소스에서 설치 (개발용)
git clone https://github.com/jjugu/Baton.git
cd Baton
pip install -e ".[dev]"

# 설치 확인
baton --help
```

## 요구사항

- Python 3.12+
- git (워크스페이스 격리 모드용)
- AI 프로바이더: `ANTHROPIC_API_KEY` (Claude) 또는 `codex login` (Codex) 또는 키 불필요 (Mock)

## 빠른 시작

```bash
# Mock 프로바이더 (API 키 불필요)
baton run --goal "hello world API 엔드포인트 추가" --provider mock --max-steps 4

# Claude 프로바이더
export ANTHROPIC_API_KEY="sk-ant-..."
baton run --goal "JWT 인증 미들웨어 구현" --provider claude --max-steps 10

# 상태 확인
baton status --job <job-id>
baton status --all
```

## 아키텍처

```
+-------------------------------------------------------------------+
|                       Orchestrator (Service)                       |
|                                                                    |
|  QUEUED -> STARTING -> PLANNING -> RUNNING -> DONE / FAILED       |
|                                                                    |
|  +----------+    +--------+    +---------+    +-----------+        |
|  | Director | -> | Leader | -> | Executor| -> | Evaluator |        |
|  | (계획)   |    | (지시) |    | (구현)  |    | (검증)    |        |
|  +----------+    +--------+    +---------+    +-----------+        |
+-------------------------------------------------------------------+
       |                |                |
  StateStore      ArtifactStore     ProcessManager
  (JSON 파일)     (.baton/artifacts)  (서브프로세스)
```

| 단계 | 역할 | 모델 | 목적 |
|------|------|------|------|
| 계획 | Director | Heavy (opus) | 목표 분석, 스프린트 계약 생성 |
| 지시 | Leader | Heavy (opus) | 다음 행동 결정: 워커 실행, 시스템 실행, 완료, 실패 |
| 구현 | Executor | Light (sonnet) | 작업 구현, 아티팩트 생성 |
| 검증 | Evaluator | Heavy (opus) | 완료 조건 충족 여부 최종 확인 |

## Claude Code MCP 연동

프로젝트의 `.mcp.json`에 추가:

```json
{
  "mcpServers": {
    "baton": {
      "type": "stdio",
      "command": "baton",
      "args": ["mcp"]
    }
  }
}
```

Claude Code에서 `/mcp` 실행 후 18개 도구 사용 가능:

| 카테고리 | 도구 |
|----------|------|
| Job 관리 | `baton_start_job`, `baton_status`, `baton_events`, `baton_artifacts`, `baton_resume`, `baton_retry`, `baton_list_jobs`, `baton_diff` |
| 체인 관리 | `baton_start_chain`, `baton_chain_status`, `baton_pause_chain`, `baton_resume_chain`, `baton_cancel_chain`, `baton_skip_chain_goal` |
| 승인/제어 | `baton_approve`, `baton_reject`, `baton_cancel`, `baton_steer` |

## CLI 명령어

| 명령어 | 설명 |
|--------|------|
| `baton run` | 새 job 시작 (`--goal`, `--provider`, `--max-steps`) |
| `baton status` | job 상태 확인 (`--job` 또는 `--all`) |
| `baton events` | job 이벤트 조회 |
| `baton artifacts` | 아티팩트 경로 조회 |
| `baton resume` | 중단된 job 재개 |
| `baton approve` / `reject` | 승인 대기 중인 작업 처리 |
| `baton retry` | 실패한 job 재시도 |
| `baton cancel` | job 취소 |
| `baton serve` | HTTP API + 웹 대시보드 시작 (`--addr 127.0.0.1:8080`) |
| `baton mcp` | MCP stdio 서버 시작 |

## HTTP API

```bash
# 서버 시작
baton serve --addr 127.0.0.1:8080

# 대시보드: http://127.0.0.1:8080/dashboard (한/영 전환 지원)
```

| 메서드 | 경로 | 설명 |
|--------|------|------|
| `POST` | `/jobs` | job 생성 |
| `GET` | `/jobs` | 전체 job 목록 |
| `GET` | `/jobs/{id}` | job 상세 |
| `POST` | `/jobs/{id}/approve` | 승인 |
| `POST` | `/jobs/{id}/cancel` | 취소 |
| `POST` | `/jobs/{id}/steer` | 지시 주입 |
| `GET` | `/jobs/{id}/events/stream` | SSE 이벤트 스트림 |
| `POST` | `/chains` | 체인 생성 |
| `GET` | `/healthz` | 헬스 체크 |

## 프로바이더 설정

```bash
# Claude (Anthropic)
export ANTHROPIC_API_KEY="sk-ant-..."
baton run --goal "..." --provider claude

# Codex (OpenAI)
baton run --goal "..." --provider codex

# Mock (테스트용, 키 불필요)
baton run --goal "..." --provider mock
```

역할별 모델 커스텀:

```json
{
  "director":  { "provider": "claude", "model": "opus" },
  "executor":  { "provider": "codex" },
  "evaluator": { "provider": "claude", "model": "opus" }
}
```

## 상태 디렉토리

```
.baton/
├── state/jobs/          # job 상태 (JSON)
├── state/chains/        # 체인 상태
├── artifacts/           # job별 아티팩트
├── leases/              # 하트비트 리스
└── serve.pid            # API 서버 PID
```

## 개발

```bash
git clone https://github.com/jjugu/Baton.git
cd Baton
pip install -e ".[dev]"
pytest                  # 342개 테스트
```

| 패키지 | 용도 |
|--------|------|
| pydantic >= 2.0 | 데이터 검증 |
| fastapi >= 0.110 | HTTP API |
| uvicorn >= 0.30 | ASGI 서버 |
| typer >= 0.12 | CLI |
| sse-starlette >= 2.0 | SSE 스트리밍 |

## 라이선스

MIT

---

<a id="baton-en"></a>

# Baton

Python asyncio multi-agent orchestration engine.

```
Director (planning) -> Leader (decisions) -> Executor (implementation) -> Evaluator (gate)
```

The Evaluator gate is inviolable -- a job cannot reach `done` status without explicit evaluator approval.

## Features

- **3-agent pipeline** with strict evaluator gate
- **3 providers** -- Claude (Anthropic), Codex (OpenAI), Mock (testing)
- **Per-role model config** -- opus for reasoning, sonnet for execution
- **Job chains** for sequential multi-step workflows
- **Workspace isolation** via git worktrees
- **MCP server** for Claude Code integration
- **HTTP API** with SSE streaming + web dashboard
- **Token usage tracking** with real-time cost monitoring
- **CLI** with 22 subcommands
- **Korean/English dashboard** with language toggle

## Installation

```bash
# From GitHub
pip install git+https://github.com/jjugu/Baton.git

# From source (development)
git clone https://github.com/jjugu/Baton.git
cd Baton
pip install -e ".[dev]"

# Verify
baton --help
```

## Requirements

- Python 3.12+
- git (for workspace isolation)
- AI provider: `ANTHROPIC_API_KEY` (Claude) or `codex login` (Codex) or none (Mock)

## Quick Start

```bash
# Mock provider (no API key)
baton run --goal "add hello world endpoint" --provider mock --max-steps 4

# Claude provider
export ANTHROPIC_API_KEY="sk-ant-..."
baton run --goal "implement JWT auth middleware" --provider claude --max-steps 10

# Check status
baton status --job <job-id>
baton status --all
```

## Architecture

```
+-------------------------------------------------------------------+
|                       Orchestrator (Service)                       |
|                                                                    |
|  QUEUED -> STARTING -> PLANNING -> RUNNING -> DONE / FAILED       |
|                                                                    |
|  +----------+    +--------+    +---------+    +-----------+        |
|  | Director | -> | Leader | -> | Executor| -> | Evaluator |        |
|  | (plan)   |    | (decide)|   | (work)  |    | (gate)    |        |
|  +----------+    +--------+    +---------+    +-----------+        |
+-------------------------------------------------------------------+
       |                |                |
  StateStore      ArtifactStore     ProcessManager
  (JSON files)    (.baton/artifacts)  (subprocess)
```

| Phase | Role | Model | Purpose |
|-------|------|-------|---------|
| Planning | Director | Heavy (opus) | Analyze goal, produce sprint contract |
| Leadership | Leader | Heavy (opus) | Decide next action |
| Execution | Executor | Light (sonnet) | Implement tasks, produce artifacts |
| Verification | Evaluator | Heavy (opus) | Gate check before marking done |

## Claude Code MCP Integration

Add to your `.mcp.json`:

```json
{
  "mcpServers": {
    "baton": {
      "type": "stdio",
      "command": "baton",
      "args": ["mcp"]
    }
  }
}
```

Run `/mcp` in Claude Code. 18 tools available:

| Category | Tools |
|----------|-------|
| Jobs | `baton_start_job`, `baton_status`, `baton_events`, `baton_artifacts`, `baton_resume`, `baton_retry`, `baton_list_jobs`, `baton_diff` |
| Chains | `baton_start_chain`, `baton_chain_status`, `baton_pause_chain`, `baton_resume_chain`, `baton_cancel_chain`, `baton_skip_chain_goal` |
| Control | `baton_approve`, `baton_reject`, `baton_cancel`, `baton_steer` |

## CLI Reference

| Command | Description |
|---------|-------------|
| `baton run` | Start a new job (`--goal`, `--provider`, `--max-steps`) |
| `baton status` | Get job status (`--job` or `--all`) |
| `baton events` | Get job events |
| `baton artifacts` | Get artifact paths |
| `baton resume` | Resume a blocked job |
| `baton approve` / `reject` | Handle pending approvals |
| `baton retry` | Retry a failed job |
| `baton cancel` | Cancel a job |
| `baton serve` | Start HTTP API + dashboard (`--addr 127.0.0.1:8080`) |
| `baton mcp` | Start MCP stdio server |

## HTTP API

```bash
# Start server
baton serve --addr 127.0.0.1:8080

# Dashboard: http://127.0.0.1:8080/dashboard (KO/EN toggle)
```

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/jobs` | Create job |
| `GET` | `/jobs` | List all jobs |
| `GET` | `/jobs/{id}` | Job details |
| `POST` | `/jobs/{id}/approve` | Approve |
| `POST` | `/jobs/{id}/cancel` | Cancel |
| `POST` | `/jobs/{id}/steer` | Inject directive |
| `GET` | `/jobs/{id}/events/stream` | SSE event stream |
| `POST` | `/chains` | Create chain |
| `GET` | `/healthz` | Health check |

## Provider Configuration

```bash
# Claude (Anthropic)
export ANTHROPIC_API_KEY="sk-ant-..."
baton run --goal "..." --provider claude

# Codex (OpenAI)
baton run --goal "..." --provider codex

# Mock (no key needed)
baton run --goal "..." --provider mock
```

Custom role profiles:

```json
{
  "director":  { "provider": "claude", "model": "opus" },
  "executor":  { "provider": "codex" },
  "evaluator": { "provider": "claude", "model": "opus" }
}
```

## State Directory

```
.baton/
├── state/jobs/          # Job state (JSON)
├── state/chains/        # Chain state
├── artifacts/           # Per-job artifacts
├── leases/              # Heartbeat leases
└── serve.pid            # API server PID
```

## Development

```bash
git clone https://github.com/jjugu/Baton.git
cd Baton
pip install -e ".[dev]"
pytest                  # 342 tests
```

| Package | Purpose |
|---------|---------|
| pydantic >= 2.0 | Data validation |
| fastapi >= 0.110 | HTTP API |
| uvicorn >= 0.30 | ASGI server |
| typer >= 0.12 | CLI |
| sse-starlette >= 2.0 | SSE streaming |

## License

MIT
