"""Cross-validate baton/provider/protocol.py against Go provider/protocol.go.

Tests:
- Schema field/required completeness for leader, worker, evaluator, planner
- Action/status enum values in schemas match Go
- Prompt builder output contains key elements
"""
from __future__ import annotations

import json

from baton.provider.protocol import (
    leader_schema,
    worker_schema,
    evaluator_schema,
    planner_schema,
)


# ---------------------------------------------------------------------------
# Leader schema
# ---------------------------------------------------------------------------

class TestLeaderSchema:
    def test_is_valid_json(self) -> None:
        data = json.loads(leader_schema())
        assert data["type"] == "object"

    def test_action_enum_matches_go(self, go_leader_actions: frozenset[str]) -> None:
        """Go leader action enum: run_worker, run_workers, run_system,
        summarize, complete, fail, blocked."""
        data = json.loads(leader_schema())
        py_actions = set(data["properties"]["action"]["enum"])
        assert py_actions == go_leader_actions

    def test_required_fields_match_go(self) -> None:
        """Go required: action, target, task_type, task_text, tasks,
        artifacts, reason, next_hint, system_action."""
        go_required = {
            "action", "target", "task_type", "task_text", "tasks",
            "artifacts", "reason", "next_hint", "system_action",
        }
        data = json.loads(leader_schema())
        assert set(data["required"]) == go_required

    def test_additional_properties_false(self) -> None:
        data = json.loads(leader_schema())
        assert data["additionalProperties"] is False

    def test_tasks_item_required(self) -> None:
        """Worker task items must have all 6 required fields."""
        data = json.loads(leader_schema())
        task_item = data["properties"]["tasks"]["items"]
        assert set(task_item["required"]) == {
            "target", "task_type", "task_text", "artifacts", "reason", "next_hint",
        }

    def test_system_action_nullable(self) -> None:
        """system_action uses anyOf[null, object] like Go."""
        data = json.loads(leader_schema())
        sa = data["properties"]["system_action"]
        assert "anyOf" in sa
        types = [v.get("type") for v in sa["anyOf"]]
        assert "null" in types
        assert "object" in types


class TestWorkerSchema:
    def test_is_valid_json(self) -> None:
        data = json.loads(worker_schema())
        assert data["type"] == "object"

    def test_status_enum_matches_go(self) -> None:
        """Go worker status: success, failed, blocked."""
        from tests.conftest import GO_WORKER_STATUSES
        data = json.loads(worker_schema())
        py_statuses = set(data["properties"]["status"]["enum"])
        assert py_statuses == GO_WORKER_STATUSES

    def test_required_fields_match_go(self) -> None:
        go_required = {
            "status", "summary", "artifacts", "blocked_reason",
            "error_reason", "next_recommended_action",
        }
        data = json.loads(worker_schema())
        assert set(data["required"]) == go_required

    def test_additional_properties_false(self) -> None:
        data = json.loads(worker_schema())
        assert data["additionalProperties"] is False


class TestEvaluatorSchema:
    def test_is_valid_json(self) -> None:
        data = json.loads(evaluator_schema())
        assert data["type"] == "object"

    def test_status_enum_matches_go(self) -> None:
        """Go evaluator status: passed, failed, blocked."""
        from tests.conftest import GO_EVALUATOR_STATUSES
        data = json.loads(evaluator_schema())
        py_statuses = set(data["properties"]["status"]["enum"])
        assert py_statuses == GO_EVALUATOR_STATUSES

    def test_required_fields_match_go(self) -> None:
        go_required = {
            "status", "passed", "score", "reason", "missing_step_types",
            "evidence", "contract_ref", "verification_report", "rubric_scores",
        }
        data = json.loads(evaluator_schema())
        assert set(data["required"]) == go_required

    def test_verification_report_nested(self) -> None:
        data = json.loads(evaluator_schema())
        vr = data["properties"]["verification_report"]
        assert vr["type"] == "object"
        vr_required = {
            "status", "passed", "reason", "evidence",
            "missing_checks", "artifacts", "contract_ref",
        }
        assert set(vr["required"]) == vr_required

    def test_rubric_scores_item(self) -> None:
        data = json.loads(evaluator_schema())
        rs = data["properties"]["rubric_scores"]["items"]
        assert set(rs["required"]) == {"axis", "score", "reasoning"}


class TestPlannerSchema:
    def test_is_valid_json(self) -> None:
        data = json.loads(planner_schema())
        assert data["type"] == "object"

    def test_required_fields_match_go(self) -> None:
        go_required = {
            "goal", "tech_stack", "workspace_dir", "summary", "product_scope",
            "non_goals", "proposed_steps", "invariants_to_preserve", "acceptance",
            "success_signals", "recommended_strictness", "recommended_max_steps",
            "verification_contract",
        }
        data = json.loads(planner_schema())
        assert set(data["required"]) == go_required

    def test_strictness_enum(self) -> None:
        data = json.loads(planner_schema())
        assert set(data["properties"]["recommended_strictness"]["enum"]) == {
            "strict", "normal", "lenient",
        }

    def test_verification_contract_nested(self) -> None:
        data = json.loads(planner_schema())
        vc = data["properties"]["verification_contract"]
        assert vc["type"] == "object"
        vc_required = {
            "version", "goal", "scope", "required_commands",
            "required_artifacts", "required_checks", "disallowed_actions",
            "max_seconds", "notes", "owner_role", "automated_checks",
        }
        assert set(vc["required"]) == vc_required

    def test_automated_checks_type_enum(self) -> None:
        """Go: grep, file_exists, file_unchanged, no_new_deps."""
        data = json.loads(planner_schema())
        ac = data["properties"]["verification_contract"]["properties"]["automated_checks"]["items"]
        assert set(ac["properties"]["type"]["enum"]) == {
            "grep", "file_exists", "file_unchanged", "no_new_deps",
        }
