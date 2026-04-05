# Go → Python Translation Patterns

gorchera Go 코드를 baton Python으로 변환할 때 사용하는 패턴 매핑.

## 1. 타입 시스템

### Struct → Pydantic BaseModel

```go
// Go
type Job struct {
    ID        string    `json:"id"`
    Goal      string    `json:"goal"`
    Status    JobStatus `json:"status"`
    CreatedAt time.Time `json:"created_at"`
}
```

```python
# Python
class Job(BaseModel):
    id: str
    goal: str
    status: JobStatus
    created_at: datetime

    model_config = ConfigDict(use_enum_values=True)
```

### String Const → str Enum

```go
type JobStatus string
const (
    JobStatusStarting JobStatus = "starting"
    JobStatusDone     JobStatus = "done"
)
```

```python
class JobStatus(str, Enum):
    STARTING = "starting"
    DONE = "done"
```

### Interface → Protocol

```go
type Adapter interface {
    Name() ProviderName
    RunLeader(ctx context.Context, job Job) (string, error)
    RunWorker(ctx context.Context, job Job, task LeaderOutput) (string, error)
}
```

```python
class Adapter(Protocol):
    def name(self) -> ProviderName: ...
    async def run_leader(self, job: Job) -> str: ...
    async def run_worker(self, job: Job, task: LeaderOutput) -> str: ...
```

## 2. 동시성

### Goroutine → asyncio.create_task

```go
go func() { s.runLoop(ctx, job) }()
```

```python
asyncio.create_task(self._run_loop(job))
```

### sync.Mutex → asyncio.Lock

```go
s.mu.Lock()
defer s.mu.Unlock()
```

```python
async with self._lock:
    ...
```

### Channel → asyncio.Queue

```go
events := make(chan Event, 100)
events <- event
```

```python
events: asyncio.Queue[Event] = asyncio.Queue(maxsize=100)
await events.put(event)
```

### WaitGroup → asyncio.gather

```go
var wg sync.WaitGroup
wg.Add(2)
go func() { defer wg.Done(); ... }()
wg.Wait()
```

```python
await asyncio.gather(task_a(), task_b())
```

## 3. 서브프로세스

### os/exec → asyncio.create_subprocess_exec

```go
cmd := exec.CommandContext(ctx, binary, args...)
cmd.Stdin = strings.NewReader(input)
cmd.Env = allowedEnv
output, err := cmd.CombinedOutput()
```

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

### error → Exception hierarchy

```go
type ProviderError struct {
    Provider ProviderName
    Kind     ProviderErrorKind
    Detail   string
}
```

```python
class ProviderError(Exception):
    def __init__(self, provider: ProviderName, kind: ErrorKind, detail: str):
        self.provider = provider
        self.kind = kind
        self.detail = detail
        super().__init__(f"{provider}: {kind.value}: {detail}")
```

### errors.As → except + isinstance

```go
var providerErr *ProviderError
if errors.As(err, &providerErr) {
    if providerErr.Kind == ErrorKindRateLimited { ... }
}
```

```python
try:
    ...
except ProviderError as e:
    if e.kind == ErrorKind.RATE_LIMITED:
        ...
```

## 5. 파일 I/O

### Atomic Write (Go의 tempfile+rename 패턴)

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

### net/http → FastAPI

```go
mux.HandleFunc("/jobs", s.handleListJobs)
mux.HandleFunc("/jobs/{jobID}", s.handleGetJob)
```

```python
@router.get("/jobs")
async def list_jobs(svc: OrchestratorService = Depends(get_service)):
    return await svc.list_jobs()

@router.get("/jobs/{job_id}")
async def get_job(job_id: str, svc: OrchestratorService = Depends(get_service)):
    return await svc.get_job(job_id)
```

## 7. 명명 규칙 변환

| Go | Python |
|----|--------|
| `RunLeader` | `run_leader` |
| `JobStatus` | `JobStatus` (클래스명 유지) |
| `runLoop` | `_run_loop` (private) |
| `MaxSteps` | `max_steps` |
| `gorchera_start_job` (MCP tool) | `baton_start_job` (도구명도 baton으로) |

## 8. 주의사항

- Go의 `context.Context` 취소는 Python에서 `asyncio.Task.cancel()` + `CancelledError`로 매핑
- Go의 `defer`는 Python의 `try/finally` 또는 `contextlib.asynccontextmanager`로 매핑
- Go의 `embed.FS`는 FastAPI의 `StaticFiles(directory=...)` 또는 `importlib.resources`로 매핑
- JSON 직렬화: Go의 `json:"field_name"` 태그는 Pydantic의 `Field(alias=...)` 또는 `model_config`로 매핑
- MCP 도구명: `gorchera_*` → `baton_*`로 변경
