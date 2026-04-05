"""Prompt builders and JSON schemas for each pipeline phase.

Schemas are strict-mode JSON Schema (all required, additionalProperties: false).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from baton.domain.types import (
    AmbitionLevel,
    Job,
    LeaderOutput,
    PipelineMode,
    RoleName,
    normalize_ambition_level,
    normalize_pipeline_mode,
)

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JSON schemas -- returned as compact strings
# ---------------------------------------------------------------------------

def leader_schema() -> str:
    return json.dumps({
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": [
                "run_worker", "run_workers", "run_system",
                "summarize", "complete", "fail", "blocked",
            ]},
            "target": {"type": "string"},
            "task_type": {"type": "string"},
            "task_text": {"type": "string"},
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string"},
                        "task_type": {"type": "string"},
                        "task_text": {"type": "string"},
                        "artifacts": {"type": "array", "items": {"type": "string"}},
                        "reason": {"type": "string"},
                        "next_hint": {"type": "string"},
                    },
                    "required": ["target", "task_type", "task_text", "artifacts", "reason", "next_hint"],
                    "additionalProperties": False,
                },
            },
            "artifacts": {"type": "array", "items": {"type": "string"}},
            "reason": {"type": "string"},
            "next_hint": {"type": "string"},
            "system_action": {
                "anyOf": [
                    {"type": "null"},
                    {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "command": {"type": "string"},
                            "args": {"type": "array", "items": {"type": "string"}},
                            "workdir": {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["type", "command", "args", "workdir", "description"],
                        "additionalProperties": False,
                    },
                ],
            },
        },
        "required": [
            "action", "target", "task_type", "task_text", "tasks",
            "artifacts", "reason", "next_hint", "system_action",
        ],
        "additionalProperties": False,
    }, separators=(",", ":"))


def planner_schema() -> str:
    return json.dumps({
        "type": "object",
        "properties": {
            "goal": {"type": "string"},
            "tech_stack": {"type": "string"},
            "workspace_dir": {"type": "string"},
            "summary": {"type": "string"},
            "product_scope": {"type": "array", "items": {"type": "string"}},
            "non_goals": {"type": "array", "items": {"type": "string"}},
            "proposed_steps": {"type": "array", "items": {"type": "string"}},
            "invariants_to_preserve": {"type": "array", "items": {"type": "string"}},
            "acceptance": {"type": "array", "items": {"type": "string"}},
            "success_signals": {"type": "array", "items": {"type": "string"}},
            "recommended_strictness": {"type": "string", "enum": ["strict", "normal", "lenient"]},
            "recommended_max_steps": {"type": "integer", "minimum": 1},
            "verification_contract": {
                "type": "object",
                "properties": {
                    "version": {"type": "integer"},
                    "goal": {"type": "string"},
                    "scope": {"type": "array", "items": {"type": "string"}},
                    "required_commands": {"type": "array", "items": {"type": "string"}},
                    "required_artifacts": {"type": "array", "items": {"type": "string"}},
                    "required_checks": {"type": "array", "items": {"type": "string"}},
                    "disallowed_actions": {"type": "array", "items": {"type": "string"}},
                    "max_seconds": {"type": "integer"},
                    "notes": {"type": "string"},
                    "owner_role": {"type": "string"},
                    "automated_checks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": [
                                    "grep", "file_exists", "file_unchanged", "no_new_deps",
                                ]},
                                "pattern": {"type": "string"},
                                "file": {"type": "string"},
                                "path": {"type": "string"},
                                "ref": {"type": "string"},
                                "description": {"type": "string"},
                            },
                            "required": ["type", "pattern", "file", "path", "ref", "description"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": [
                    "version", "goal", "scope", "required_commands",
                    "required_artifacts", "required_checks", "disallowed_actions",
                    "max_seconds", "notes", "owner_role", "automated_checks",
                ],
                "additionalProperties": False,
            },
        },
        "required": [
            "goal", "tech_stack", "workspace_dir", "summary", "product_scope",
            "non_goals", "proposed_steps", "invariants_to_preserve", "acceptance",
            "success_signals", "recommended_strictness", "recommended_max_steps",
            "verification_contract",
        ],
        "additionalProperties": False,
    }, separators=(",", ":"))


def evaluator_schema() -> str:
    return json.dumps({
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["passed", "failed", "blocked"]},
            "passed": {"type": "boolean"},
            "score": {"type": "integer"},
            "reason": {"type": "string"},
            "missing_step_types": {"type": "array", "items": {"type": "string"}},
            "evidence": {"type": "array", "items": {"type": "string"}},
            "contract_ref": {"type": "string"},
            "verification_report": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["passed", "failed", "blocked"]},
                    "passed": {"type": "boolean"},
                    "reason": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "missing_checks": {"type": "array", "items": {"type": "string"}},
                    "artifacts": {"type": "array", "items": {"type": "string"}},
                    "contract_ref": {"type": "string"},
                },
                "required": [
                    "status", "passed", "reason", "evidence",
                    "missing_checks", "artifacts", "contract_ref",
                ],
                "additionalProperties": False,
            },
            "rubric_scores": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "axis": {"type": "string"},
                        "score": {"type": "number"},
                        "reasoning": {"type": "string"},
                    },
                    "required": ["axis", "score", "reasoning"],
                    "additionalProperties": False,
                },
            },
        },
        "required": [
            "status", "passed", "score", "reason", "missing_step_types",
            "evidence", "contract_ref", "verification_report", "rubric_scores",
        ],
        "additionalProperties": False,
    }, separators=(",", ":"))


def worker_schema() -> str:
    return json.dumps({
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["success", "failed", "blocked"]},
            "summary": {"type": "string"},
            "artifacts": {"type": "array", "items": {"type": "string"}},
            "blocked_reason": {"type": "string"},
            "error_reason": {"type": "string"},
            "next_recommended_action": {"type": "string"},
        },
        "required": [
            "status", "summary", "artifacts", "blocked_reason",
            "error_reason", "next_recommended_action",
        ],
        "additionalProperties": False,
    }, separators=(",", ":"))


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def build_planner_prompt(job: Job) -> str:
    planner_job = job.model_copy(update={"ambition_level": ""})
    payload = planner_job.model_dump_json(indent=2)

    chain_section = ""
    if job.chain_context and (job.chain_context.summary or job.chain_context.evaluator_report_ref):
        chain_section = (
            f"\n\n## Previous chain step results\n\n"
            f"Summary: {job.chain_context.summary}\n"
            f"Evaluator report: {job.chain_context.evaluator_report_ref}\n"
        )

    rp = job.role_profiles
    lines = ["\nRole profiles (which models handle each role):"]
    for name, profile in [
        ("director", rp.profile_for(RoleName.DIRECTOR, job.provider)),
        ("executor", rp.executor),
        ("reviewer", rp.reviewer),
        ("evaluator", rp.evaluator),
    ]:
        model = profile.model or "default"
        provider = profile.provider or "default"
        lines.append(f"- {name}: {provider}/{model}")
    role_section = "\n".join(lines)

    base = f"""\
TASK: You are a director planning component operating under an orchestrator supervisor. The supervisor manages the overall workflow, and you define the execution plan, sprint contract, and verification expectations that the director dispatch loop will enforce. You do not perform implementation yourself.
The job data below is complete. Plan it now -- do not ask for more input.
Output only a JSON object matching the schema. No conversation, no preamble.

The goal to plan: {job.goal}

Full job state:
{payload}
{chain_section}{role_section}

## Codebase analysis (do this first)
Before writing the spec, read the relevant source files in the workspace to understand current implementation state. List specific files you examined and key findings. This grounds your plan in reality rather than assumptions.

## Concrete improvement descriptions
For each planned change, explain what currently exists, what is wrong or missing, and the specific improvement. Avoid vague descriptions. The executor and reviewer must be able to understand exactly what to change and why.

## Invariants to preserve
List the existing behaviors, contracts, or boundaries that downstream workers must keep intact while making the change. Use an empty array when there are no meaningful invariants.

## Acceptance criteria
Include measurable acceptance criteria for each deliverable. Each criterion must be verifiable by the evaluator. Criteria like 'code is clean' are not acceptable -- use criteria like 'function X returns Y when given Z' or 'go test ./... exits 0'.

Output requirements (all fields required in JSON):
- goal: restate the objective concisely
- summary: one-paragraph plan of how to achieve the goal
- tech_stack: technologies involved (empty string if none)
- workspace_dir: absolute workspace path from job state
- product_scope: array of what is in scope
- non_goals: array of what is explicitly out of scope
- proposed_steps: ordered array of implementation steps
- invariants_to_preserve: array of behaviors/contracts that must not break during implementation (use [] when none apply)
- acceptance: array of measurable acceptance criteria
- success_signals: observable signals that indicate success
- recommended_strictness: recommend "strict", "normal", or "lenient"
- recommended_max_steps: recommend the number of execution steps needed
- verification_contract: object with version=1, goal=what to verify, required_artifacts=files that must exist after execution"""

    return _apply_prompt_overrides(base.strip(), "director", job.workspace_dir, job.prompt_overrides)


def build_leader_prompt(job: Job) -> str:
    payload = _build_leader_job_payload(job)
    contract_payload = "{}"
    strictness_level = job.strictness_level.strip()

    invariants_section = f"Planning invariants to preserve:\n{_format_prompt_list(job.constraints, '- None provided.')}\n\n"
    supervisor_section = ""
    if job.supervisor_directive.strip():
        supervisor_section = f"Supervisor directive:\n{job.supervisor_directive}\n\n"

    schema_retry_section = ""
    if job.schema_retry_hint.strip():
        schema_retry_section = (
            f"CORRECTION REQUIRED: Your previous response failed schema validation: "
            f"{job.schema_retry_hint}\nRespond with valid JSON matching the required schema.\n\n"
        )

    if job.sprint_contract_ref.strip():
        try:
            data = Path(job.sprint_contract_ref).read_text()
            contract_payload = data
            parsed = json.loads(data)
            if parsed.get("strictness_level", "").strip():
                strictness_level = parsed["strictness_level"].strip()
        except (OSError, json.JSONDecodeError):
            pass

    pipeline_mode = normalize_pipeline_mode(job.pipeline_mode)
    completion_rules = [
        "Completion rules:",
        '- Use action="complete" only when the sprint contract is satisfied and the goal is fully achieved.',
        "- Engine-managed build/test run automatically after each successful implement step.",
        "- If required step coverage is missing, dispatch the missing work instead of choosing complete.",
        "- Do NOT use summarize as a substitute for complete.",
    ]

    if pipeline_mode == PipelineMode.LIGHT:
        completion_rules.append(
            "- Pipeline mode is light. After implement succeeds and engine checks pass, the evaluator performs quick verification."
        )
    elif pipeline_mode == PipelineMode.FULL:
        completion_rules.append(
            "- Pipeline mode is full. After implement succeeds and engine checks pass, the evaluator performs exhaustive code review."
        )
    else:
        completion_rules.append(
            "- After implement succeeds and engine checks pass, the evaluator performs thorough code review."
        )

    if strictness_level.lower() == "strict":
        completion_rules.append(
            "- Strict mode is active. Do not choose complete until every required director stage has succeeded."
        )

    base = f"""\
TASK: You are a director dispatch component operating under an orchestrator supervisor.
The job data below is complete. Decide and output the next action now -- do not ask for input.
Output only a JSON object matching the schema. No conversation, no preamble.

Job goal: {job.goal}

Pipeline mode: {pipeline_mode}

Valid actions (choose exactly one):
- run_worker: assign a task to a single worker (target: "B", "C", or "D")
- run_workers: assign tasks to exactly 2 workers in parallel (disjoint targets)
- run_system: run an allowlisted system command (target must be "SYS")
- summarize: record a summary of progress so far
- complete: mark the job as done (only when the goal is fully achieved)
- fail: mark the job as failed (when it cannot proceed)
- blocked: mark the job as blocked (when external information is needed)

{chr(10).join(completion_rules)}

{invariants_section}{supervisor_section}{schema_retry_section}Current job state:
{payload}

Sprint contract:
{contract_payload}
If the supervisor directive section is present, follow it with highest priority."""

    return _apply_prompt_overrides(base.strip(), "director", job.workspace_dir, job.prompt_overrides)


def build_evaluator_prompt(job: Job) -> str:
    contract_payload = "{}"
    if job.verification_contract is not None:
        contract_payload = job.verification_contract.model_dump_json(indent=2)

    rubric_section = ""
    if job.verification_contract and job.verification_contract.rubric_axes:
        lines = [
            "\nRUBRIC SCORING:",
            "Score each axis on a 0.0 to 1.0 scale and return results in rubric_scores.",
            "Axes to score:",
        ]
        for axis in job.verification_contract.rubric_axes:
            lines.append(f"- {axis.name} (min_threshold: {axis.min_threshold:.2f}, weight: {axis.weight:.2f})")
        rubric_section = "\n".join(lines)

    pipeline_mode = normalize_pipeline_mode(job.pipeline_mode)
    if pipeline_mode == PipelineMode.LIGHT:
        depth = "Verification depth: QUICK. Check engine results and verify goal satisfaction."
    elif pipeline_mode == PipelineMode.FULL:
        depth = "Verification depth: EXHAUSTIVE. Read all changed files plus adjacent code."
    else:
        depth = "Verification depth: THOROUGH. Read all changed files, check edge cases."

    strictness = job.strictness_level.strip().lower()
    if strictness == "lenient":
        strictness_text = "Strictness: LENIENT. Your default decision is FAIL. Pass only when you see nothing obviously wrong."
    elif strictness == "strict":
        strictness_text = "Strictness: STRICT. You are an adversarial reviewer. Your default decision is FAIL."
    else:
        strictness_text = "Strictness: NORMAL. Your default decision is FAIL. Fail for any concrete defect."

    schema_retry_section = ""
    if job.schema_retry_hint.strip():
        schema_retry_section = (
            f"\nCORRECTION REQUIRED: Your previous response failed schema validation: "
            f"{job.schema_retry_hint}\nRespond with valid JSON matching the required schema.\n"
        )

    compact_payload = _build_compact_evaluator_payload(job)

    base = f"""\
TASK: You are an evaluator for an orchestrator-managed job. You verify results against the verification contract and report pass/fail/blocked.
The job data below is complete. Evaluate it now. Output only a JSON object matching the schema.

ROLE:
- You are a release gate, not a cheerleader.
- {_ambition_evaluation_guidance(job.ambition_level, job.ambition_text)}
- {depth}
- {strictness_text}

Job goal: {job.goal}

PROCEDURE (mandatory):
1. Read diff_summary and error_reason in each step.
2. Open and read artifact files.
3. Read actual source files that were changed.
4. Check the verification contract below.
5. Decide: status="passed", "failed", or "blocked".
{rubric_section}{schema_retry_section}
Current job state:
{compact_payload}

Verification contract:
{contract_payload}"""

    return _apply_prompt_overrides(base.strip(), "evaluator", job.workspace_dir, job.prompt_overrides)


def build_worker_prompt(job: Job, task: LeaderOutput) -> str:
    task_payload = task.model_dump_json(indent=2)
    task_ctx = _parse_worker_task_context(task.task_text, job.leader_context_summary)
    invariants_section = _format_prompt_list(job.constraints, "- None provided.")

    schema_retry_section = ""
    if job.schema_retry_hint.strip():
        schema_retry_section = (
            f"\nCORRECTION REQUIRED: Your previous response failed schema validation: "
            f"{job.schema_retry_hint}\nRespond with valid JSON matching the required schema.\n"
        )

    build_cmd = job.engine_build_cmd.strip() or "go build ./..."
    test_cmd = job.engine_test_cmd.strip() or "go test ./..."
    compact_payload = _build_compact_executor_payload(job, task)

    base = f"""\
TASK: You are an executor worker assigned by the director. You perform the task described below.
The assigned task below is complete and ready to execute. Do it now -- do not ask for input.
Output only a JSON object matching the schema. No conversation, no preamble.
status MUST be one of: success, failed, blocked.
{schema_retry_section}
Overall job goal: {job.goal}

Task objective:
{task_ctx.objective}

Task why:
{task_ctx.why}

Invariants to preserve:
{invariants_section}

Scope boundary:
{task_ctx.scope_boundary}

Autonomy guidance:
{_ambition_instruction(job.ambition_level, job.ambition_text)}

Assigned task payload:
{task_payload}

Self-check before reporting success:
- Run: {build_cmd}
- Run: {test_cmd}
- Fix any build errors or test failures yourself before reporting.

Job state:
{compact_payload}"""

    return _apply_prompt_overrides(base.strip(), "executor", job.workspace_dir, job.prompt_overrides)


# ---------------------------------------------------------------------------
# Ambition guidance
# ---------------------------------------------------------------------------

def _ambition_instruction(level: str, ambition_text: str) -> str:
    normalized = normalize_ambition_level(level)
    match normalized:
        case "low":
            base = "Do exactly what is described. Do not improve, refactor, or extend beyond the explicit task."
        case "high":
            base = "Achieve the goal and go further. Propose and implement structural improvements."
        case "extreme":
            base = "Build as if this will be open-sourced. Minimum bar: fuzz testing, benchmarks, explicit edge case handling."
        case "custom":
            if not ambition_text.strip():
                return "Complete the task. If you notice directly related improvements, include them but stay within scope."
            return f"Autonomy guidance:\n{ambition_text.strip()}"
        case _:
            base = "Complete the task. If you notice directly related improvements, include them but stay within scope."
    if ambition_text.strip():
        return f"Autonomy guidance:\n{ambition_text.strip()}\n\n{base}"
    return base


def _ambition_evaluation_guidance(level: str, ambition_text: str) -> str:
    normalized = normalize_ambition_level(level)
    match normalized:
        case "low":
            base = "Ambition level is low. Judge against the explicit task only."
        case "high":
            base = "Ambition level is high. Accept justified scope expansion."
        case "extreme":
            base = "Ambition level is extreme. Demand production-grade quality."
        case "custom":
            if not ambition_text.strip():
                return "Ambition level is medium. Accept directly related improvements."
            return f"Autonomy guidance:\n{ambition_text.strip()}"
        case _:
            base = "Ambition level is medium. Accept directly related improvements."
    if ambition_text.strip():
        return f"Autonomy guidance:\n{ambition_text.strip()}\n\n{base}"
    return base


# ---------------------------------------------------------------------------
# Context compaction helpers
# ---------------------------------------------------------------------------

def _build_leader_job_payload(job: Job) -> str:
    j = job.model_copy(update={"supervisor_directive": ""})
    mode = (j.context_mode or "full").strip().lower()
    if mode == "auto":
        mode = _auto_context_mode(j.role_profiles.leader.model, len(j.steps))
    if mode == "summary":
        return _build_summary_payload(j)
    if mode == "minimal":
        return _build_minimal_payload(j)
    return j.model_dump_json(indent=2)


def _auto_context_mode(model: str, step_count: int) -> str:
    if step_count < 10:
        return "full"
    if step_count <= 20:
        return "summary"
    return "minimal"


def _build_summary_payload(job: Job) -> str:
    steps = []
    for i, s in enumerate(job.steps):
        summary = s.summary
        if i < len(job.steps) - 2 and len(summary) > 80:
            summary = summary[:80] + "..."
        entry: dict = {"index": s.index, "task_type": s.task_type, "status": s.status}
        if i >= len(job.steps) - 2:
            entry["summary"] = s.summary
            entry["task_text"] = s.task_text
        else:
            entry["summary"] = summary
        steps.append(entry)
    out = {
        "goal": job.goal,
        "summary": job.summary,
        "leader_context_summary": job.leader_context_summary,
        "constraints": list(job.constraints),
        "strictness_level": job.strictness_level,
        "context_mode": "summary",
        "status": job.status,
        "current_step": job.current_step,
        "max_steps": job.max_steps,
        "token_usage": job.token_usage.model_dump(),
        "steps": steps,
    }
    return json.dumps(out, indent=2)


def _build_minimal_payload(job: Job) -> str:
    succeeded = failed = blocked = active = 0
    for s in job.steps:
        match s.status:
            case "succeeded": succeeded += 1
            case "failed": failed += 1
            case "blocked": blocked += 1
            case _: active += 1
    last_step = None
    if job.steps:
        last = job.steps[-1]
        last_step = {
            "index": last.index,
            "task_type": last.task_type,
            "status": last.status,
            "summary": last.summary,
            "task_text": last.task_text,
        }
    out = {
        "goal": job.goal,
        "summary": job.summary,
        "leader_context_summary": job.leader_context_summary,
        "constraints": list(job.constraints),
        "strictness_level": job.strictness_level,
        "context_mode": "minimal",
        "status": job.status,
        "current_step": job.current_step,
        "max_steps": job.max_steps,
        "succeeded_steps": succeeded,
        "failed_steps": failed,
        "blocked_steps": blocked,
        "active_steps": active,
        "last_step": last_step,
    }
    return json.dumps(out, indent=2)


def _build_compact_executor_payload(job: Job, task: LeaderOutput) -> str:
    prev_failure = None
    for s in reversed(job.steps):
        if s.status in ("failed", "blocked"):
            reason = s.error_reason or s.blocked_reason or s.summary
            if reason:
                prev_failure = {
                    "step_index": s.index,
                    "task_type": s.task_type,
                    "reason": reason,
                }
            break
    out: dict = {
        "job_id": job.id,
        "workspace_dir": job.workspace_dir,
        "workspace_mode": job.workspace_mode,
    }
    if prev_failure:
        out["previous_failure"] = prev_failure
    return json.dumps(out, indent=2)


def _build_compact_evaluator_payload(job: Job) -> str:
    steps = []
    all_changed = []
    for s in job.steps:
        summary = s.summary
        if len(summary) > 500:
            summary = summary[:500] + "..."
        step_data: dict = {
            "index": s.index,
            "task_type": s.task_type,
            "status": s.status,
            "summary": summary,
            "diff_summary": s.diff_summary,
            "error_reason": s.error_reason,
            "artifacts": s.artifacts,
            "changed_files": [cf.model_dump() for cf in s.changed_files],
        }
        steps.append(step_data)
        all_changed.extend(cf.model_dump() for cf in s.changed_files)

    out: dict = {
        "job_id": job.id,
        "goal": job.goal,
        "status": job.status,
        "current_step": job.current_step,
        "summary": job.summary,
        "role_profiles": job.role_profiles.model_dump(),
        "steps": steps,
    }
    if job.pre_check_results:
        out["automated_check_results"] = [r.model_dump() for r in job.pre_check_results]
    if all_changed:
        out["changed_files"] = all_changed
    return json.dumps(out, indent=2)


# ---------------------------------------------------------------------------
# Task text parsing
# ---------------------------------------------------------------------------

class _WorkerTaskContext:
    __slots__ = ("objective", "why", "scope_boundary")

    def __init__(self, objective: str, why: str, scope_boundary: str) -> None:
        self.objective = objective
        self.why = why
        self.scope_boundary = scope_boundary


def _parse_worker_task_context(task_text: str, fallback_why: str) -> _WorkerTaskContext:
    ctx_obj = task_text.strip()
    sections: dict[str, list[str]] = {"objective": [], "why": [], "scope_boundary": []}
    current = "objective"
    seen_structured = False
    for line in task_text.split("\n"):
        section, value, ok = _parse_task_section_header(line)
        if ok:
            current = section
            seen_structured = True
            if value:
                sections[current].append(value)
            continue
        sections[current].append(line)

    if seen_structured:
        obj = "\n".join(sections["objective"]).strip()
        if obj:
            ctx_obj = obj
        why = "\n".join(sections["why"]).strip()
        scope = "\n".join(sections["scope_boundary"]).strip()
    else:
        why = ""
        scope = ""

    if not ctx_obj:
        ctx_obj = task_text.strip()
    if not why:
        why = fallback_why.strip() or "Not provided."
    if not scope:
        scope = "Only perform the assigned task and stay within the stated file, workspace, and contract limits."

    return _WorkerTaskContext(ctx_obj, why, scope)


def _parse_task_section_header(line: str) -> tuple[str, str, bool]:
    trimmed = line.strip()
    if not trimmed:
        return "", "", False
    content = trimmed.lstrip("-*# ")
    normalized = content.lower()
    candidates = [
        (["task why", "task_why", "why"], "why"),
        (["scope boundary", "scope_boundary", "scope"], "scope_boundary"),
        (["objective", "task", "assigned task"], "objective"),
    ]
    for labels, section in candidates:
        for label in labels:
            if normalized == label:
                return section, "", True
            prefix = label + ":"
            if normalized.startswith(prefix):
                return section, content[len(prefix):].strip(), True
    return "", "", False


# ---------------------------------------------------------------------------
# Prompt override application
# ---------------------------------------------------------------------------

def _load_prompt_override(workspace_dir: str, role: str) -> tuple[str, bool]:
    """Load .baton/prompts/<role>.md from workspace. Returns (content, is_replace)."""
    if not workspace_dir.strip():
        return "", False
    path = Path(workspace_dir) / ".baton" / "prompts" / f"{role}.md"
    try:
        data = path.read_text(encoding="utf-8")
    except OSError:
        return "", False
    first_line, _, rest = data.partition("\n")
    if first_line.strip() == "# REPLACE":
        return rest.lstrip("\n"), True
    return data, False


def _apply_prompt_overrides(
    base: str,
    role: str,
    workspace_dir: str,
    job_overrides: dict[str, str] | None,
) -> str:
    ws_content, is_replace = _load_prompt_override(workspace_dir, role)
    result = base
    if is_replace:
        result = ws_content.strip()
    elif ws_content:
        result = ws_content.strip() + "\n\n" + base

    if job_overrides:
        fragment = job_overrides.get(role, "").strip()
        if fragment:
            result = fragment + "\n\n" + result

    return result


def _format_prompt_list(values: list[str], empty: str) -> str:
    items = [v.strip() for v in values if v.strip()]
    if not items:
        return empty
    return "\n".join(f"- {v}" for v in items)


def _first_non_empty(*values: str) -> str:
    for v in values:
        if v.strip():
            return v
    return ""
