# CLAUDE.md

Baton — Python asyncio 기반 멀티 에이전트 오케스트레이션 엔진.

## Build & Verify

```bash
pip install -e ".[dev]"
pytest
python -m baton --help
```

## Architecture

- **3-agent pipeline**: director → executor → [engine build/test] → evaluator
- **Python 3.12+**, Pydantic v2, FastAPI, Typer, asyncio

## Core Principles

- Evaluator gate: 절대 우회하지 않는다 — done은 반드시 evaluateCompletion()을 통과해야 도달
- 에이전트 간 전체 대화 로그 전달 금지 — artifact + summary만 전달
- Executor는 워커를 스폰하지 않는다 — 병렬성은 오케스트레이터가 관리
- 승인이 필요한 작업은 자동 통과 금지
- ASCII only — 코드/출력에 비ASCII 문자 사용 금지
- Comment "why", not "what"

## Harness

3명 에이전트 팀으로 빌드:
- **core-dev**: 도메인, 저장소, 오케스트레이터, provider
- **interface-dev**: MCP, HTTP API, CLI, 웹 대시보드
- **qa-inspector**: 통합 검증, 테스트

오케스트레이터 스킬: `.claude/skills/baton-orchestrator/`

## Code Entry Points

- `baton/cli.py` — CLI (Typer)
- `baton/orchestrator/service.py` — 코어 루프
- `baton/provider/base.py` — 어댑터 인터페이스
- `baton/provider/protocol.py` — 프롬프트/스키마
- `baton/mcp/server.py` — MCP 서버
- `baton/api/server.py` — HTTP API

## MCP Tool Naming

MCP 도구는 `baton_*` 네이밍 (18개 도구)

## Rules

- 코드 변경 후 반드시 `pytest` 실행
- 행동 변경 시 docs/ 업데이트
