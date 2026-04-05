"""Runtime types -- request/result/process models.

Ported from gorchera/internal/runtime/types.go.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Category(str, Enum):
    BUILD = "build"
    TEST = "test"
    LINT = "lint"
    SEARCH = "search"
    COMMAND = "command"


class Request(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    category: Category
    command: str
    args: list[str] = Field(default_factory=list)
    dir: str = ""
    env: list[str] = Field(default_factory=list)
    timeout_seconds: float = 300.0
    max_output_bytes: int = 1 << 20


class StartRequest(Request):
    name: str = ""
    log_dir: str = ""
    port: int = 0


class ProcessState(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    EXITED = "exited"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ProcessHandle(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    pid: int
    name: str = ""
    category: Category = Category.COMMAND
    command: str = ""
    args: list[str] = Field(default_factory=list)
    port: int = 0
    log_path: str = ""
    state: ProcessState = ProcessState.UNKNOWN
    started_at: datetime = Field(default_factory=lambda: datetime.min)
    finished_at: datetime = Field(default_factory=lambda: datetime.min)
    exit_code: int = 0
    running: bool = False
    error: str = ""


class Result(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    category: Category = Category.COMMAND
    command: str = ""
    args: list[str] = Field(default_factory=list)
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    started_at: datetime = Field(default_factory=lambda: datetime.min)
    finished_at: datetime = Field(default_factory=lambda: datetime.min)
    duration_seconds: float = 0.0
    timed_out: bool = False
    truncated_stdout: bool = False
    truncated_stderr: bool = False
