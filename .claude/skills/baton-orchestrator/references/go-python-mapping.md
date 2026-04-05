# Baton Python Implementation Patterns

Baton Python 코드베이스에서 사용하는 핵심 구현 패턴.

## 1. 타입 시스템

### Pydantic BaseModel

```python
class Job(BaseModel):
    id: str
    goal: str
    status: JobStatus
    created_at: datetime

    model_config = ConfigDict(use_enum_values=True)
```

### str Enum

```python
class JobStatus(str, Enum):
    STARTING = "starting"
    DONE = "done"
```

### Protocol (인터페이스)

```python
class Adapter(Protocol):
    def name(self) -> ProviderName: ...
    async def run_leader(self, job: Job) -> str: ...
    async def run_worker(self, job: Job, task: LeaderOutput) -> str: ...
```

## 2. 동시성

### asyncio.create_task

```python
asyncio.create_task(self._run_loop(job))
```

### asyncio.Lock

```python
async with self._lock:
    ...
```

### asyncio.Queue

```python
events: asyncio.Queue[Event] = asyncio.Queue(maxsize=100)
await events.put(event)
```

### asyncio.gather

```python
await asyncio.gather(task_a(), task_b())
```

## 3. 서브프로세스

### asyncio.create_subprocess_exec

```python
proc = await asyncio.create_subprocess_exec(
    binary, *args,
    stdin=asyncio.subprocess.PIPE,
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
    env=allowed_env,
)
stdout, stderr = await proc.communicate(input=input_bytes)
```

## 4. 에러 처리

### Exception hierarchy

```python
class ProviderError(Exception):
    def __init__(self, provider: ProviderName, kind: ErrorKind, detail: str):
        self.provider = provider
        self.kind = kind
        self.detail = detail
        super().__init__(f"{provider}: {kind.value}: {detail}")
```

### except + isinstance

```python
try:
    ...
except ProviderError as e:
    if e.kind == ErrorKind.RATE_LIMITED:
        ...
```

## 5. 파일 I/O

### Atomic Write (tempfile + rename)

```python
import tempfile
import os

def atomic_write(path: Path, data: bytes) -> None:
    dir_ = path.parent
    dir_.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(dir_))
    try:
        os.write(fd, data)
        os.close(fd)
        os.replace(tmp, str(path))  # atomic on POSIX; best-effort on Windows
    except:
        os.close(fd) if not os.get_inheritable(fd) else None
        os.unlink(tmp)
        raise
```

## 6. HTTP/API

### FastAPI

```python
@router.get("/jobs")
async def list_jobs(svc: OrchestratorService = Depends(get_service)):
    return await svc.list_jobs()

@router.get("/jobs/{job_id}")
async def get_job(job_id: str, svc: OrchestratorService = Depends(get_service)):
    return await svc.get_job(job_id)
```

## 7. 명명 규칙

| 카테고리 | 규칙 | 예시 |
|---------|------|------|
| 클래스 | PascalCase | `JobStatus` |
| public 메서드 | snake_case | `run_leader` |
| private 메서드 | _snake_case | `_run_loop` |
| 상수/필드 | snake_case | `max_steps` |
| MCP 도구 | baton_ prefix | `baton_start_job` |

## 8. 주의사항

- 비동기 취소는 `asyncio.Task.cancel()` + `CancelledError`로 처리
- 리소스 정리는 `try/finally` 또는 `contextlib.asynccontextmanager` 사용
- 정적 파일은 FastAPI의 `StaticFiles(directory=...)` 또는 `importlib.resources` 사용
- JSON 직렬화: Pydantic의 `Field(alias=...)` 또는 `model_config` 활용
- MCP 도구명: `baton_*` 네이밍 사용
