"""Cross-validate baton/mcp/server.py against Go mcp/server.go.

Tests:
- All 18 MCP tools present with correct baton_* names
- Required parameters match Go tool definitions
- Tool list order matches Go
- JSON-RPC response format
- Terminal state event kind sets match Go
"""
from __future__ import annotations

from baton.mcp.server import (
    _tool_list,
    _is_terminal_job_status,
    _MIGHT_PRODUCE_TERMINAL,
    _CLEARS_TERMINAL_STATE,
    _ok_resp,
    _error_resp,
    _text_result,
    _status_wait_duration,
    STATUS_WAIT_DEFAULT,
    STATUS_WAIT_TIMEOUT,
)


# ---------------------------------------------------------------------------
# Tool list completeness (18 tools, 1:1 with Go)
# ---------------------------------------------------------------------------

class TestToolList:
    def test_count(self) -> None:
        tools = _tool_list()
        assert len(tools) == 18

    def test_names_match_baton_convention(self, baton_mcp_tool_names: list[str]) -> None:
        """All tools should use the baton_* naming convention."""
        tools = _tool_list()
        actual_names = [t["name"] for t in tools]
        assert actual_names == baton_mcp_tool_names

    def test_all_tools_present(self, go_mcp_tool_names: list[str]) -> None:
        """Every expected tool is present."""
        tools = _tool_list()
        actual_names = {t["name"] for t in tools}
        for name in go_mcp_tool_names:
            assert name in actual_names, f"Missing tool: {name}"

    def test_order_matches_reference(self, go_mcp_tool_names: list[str]) -> None:
        """Tool order should match the reference list."""
        tools = _tool_list()
        actual_names = [t["name"] for t in tools]
        assert actual_names == go_mcp_tool_names


class TestToolRequiredParams:
    """Verify required parameters match Go tool definitions."""

    def _tool_by_name(self, name: str) -> dict:
        for t in _tool_list():
            if t["name"] == name:
                return t
        raise ValueError(f"Tool not found: {name}")

    def test_start_job_required_goal(self) -> None:
        t = self._tool_by_name("baton_start_job")
        assert t["inputSchema"]["required"] == ["goal"]

    def test_start_chain_required_goals_workspace(self) -> None:
        t = self._tool_by_name("baton_start_chain")
        assert set(t["inputSchema"]["required"]) == {"goals", "workspace_dir"}

    def test_list_jobs_no_required(self) -> None:
        t = self._tool_by_name("baton_list_jobs")
        assert "required" not in t["inputSchema"] or t["inputSchema"].get("required") is None

    def test_status_required_job_id(self) -> None:
        t = self._tool_by_name("baton_status")
        assert t["inputSchema"]["required"] == ["job_id"]

    def test_chain_status_required(self) -> None:
        t = self._tool_by_name("baton_chain_status")
        assert t["inputSchema"]["required"] == ["chain_id"]

    def test_pause_chain_required(self) -> None:
        t = self._tool_by_name("baton_pause_chain")
        assert t["inputSchema"]["required"] == ["chain_id"]

    def test_resume_chain_required(self) -> None:
        t = self._tool_by_name("baton_resume_chain")
        assert t["inputSchema"]["required"] == ["chain_id"]

    def test_cancel_chain_required(self) -> None:
        t = self._tool_by_name("baton_cancel_chain")
        assert t["inputSchema"]["required"] == ["chain_id"]

    def test_skip_chain_goal_required(self) -> None:
        t = self._tool_by_name("baton_skip_chain_goal")
        assert t["inputSchema"]["required"] == ["chain_id"]

    def test_events_required(self) -> None:
        t = self._tool_by_name("baton_events")
        assert t["inputSchema"]["required"] == ["job_id"]

    def test_artifacts_required(self) -> None:
        t = self._tool_by_name("baton_artifacts")
        assert t["inputSchema"]["required"] == ["job_id"]

    def test_approve_required(self) -> None:
        t = self._tool_by_name("baton_approve")
        assert t["inputSchema"]["required"] == ["job_id"]

    def test_reject_required(self) -> None:
        t = self._tool_by_name("baton_reject")
        assert t["inputSchema"]["required"] == ["job_id"]

    def test_retry_required(self) -> None:
        t = self._tool_by_name("baton_retry")
        assert t["inputSchema"]["required"] == ["job_id"]

    def test_cancel_required(self) -> None:
        t = self._tool_by_name("baton_cancel")
        assert t["inputSchema"]["required"] == ["job_id"]

    def test_resume_required(self) -> None:
        t = self._tool_by_name("baton_resume")
        assert t["inputSchema"]["required"] == ["job_id"]

    def test_steer_required(self) -> None:
        t = self._tool_by_name("baton_steer")
        assert set(t["inputSchema"]["required"]) == {"job_id", "message"}

    def test_diff_required(self) -> None:
        t = self._tool_by_name("baton_diff")
        assert t["inputSchema"]["required"] == ["job_id"]


class TestStartJobSchemaProperties:
    """Verify start_job has all Go-equivalent parameters."""

    def test_all_go_params_present(self) -> None:
        go_params = {
            "goal", "provider", "workspace_dir", "workspace_mode", "max_steps",
            "pipeline_mode", "strictness_level", "ambition_level", "ambition_text",
            "context_mode", "role_overrides", "pre_build_commands",
            "engine_build_cmd", "engine_test_cmd", "prompt_overrides",
        }
        tools = _tool_list()
        start_job = next(t for t in tools if t["name"] == "baton_start_job")
        py_params = set(start_job["inputSchema"]["properties"].keys())
        assert go_params == py_params


# ---------------------------------------------------------------------------
# Terminal state event kinds (from Go mightProduceTerminalState / clearsTerminalNotificationState)
# ---------------------------------------------------------------------------

class TestTerminalEventKinds:
    def test_might_produce_terminal(self) -> None:
        """Go: job_blocked, job_failed, job_completed, job_cancelled, job_interrupted."""
        expected = {"job_blocked", "job_failed", "job_completed", "job_cancelled", "job_interrupted"}
        assert _MIGHT_PRODUCE_TERMINAL == expected

    def test_clears_terminal_state(self) -> None:
        """Go: job_created, job_resumed, job_retry_requested, job_approved."""
        expected = {"job_created", "job_resumed", "job_retry_requested", "job_approved"}
        assert _CLEARS_TERMINAL_STATE == expected


class TestTerminalJobStatus:
    def test_done_is_terminal(self) -> None:
        assert _is_terminal_job_status("done")

    def test_failed_is_terminal(self) -> None:
        assert _is_terminal_job_status("failed")

    def test_blocked_is_terminal(self) -> None:
        assert _is_terminal_job_status("blocked")

    def test_running_is_not_terminal(self) -> None:
        assert not _is_terminal_job_status("running")


# ---------------------------------------------------------------------------
# JSON-RPC response format
# ---------------------------------------------------------------------------

class TestJSONRPCFormat:
    def test_ok_resp(self) -> None:
        resp = _ok_resp(1, {"key": "value"})
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        assert resp["result"] == {"key": "value"}
        assert "error" not in resp

    def test_error_resp(self) -> None:
        resp = _error_resp(2, -32602, "invalid params")
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 2
        assert resp["error"]["code"] == -32602
        assert resp["error"]["message"] == "invalid params"

    def test_text_result_format(self) -> None:
        result = _text_result("hello")
        assert result["content"][0]["type"] == "text"
        assert result["content"][0]["text"] == "hello"


# ---------------------------------------------------------------------------
# Wait duration logic
# ---------------------------------------------------------------------------

class TestStatusWaitDuration:
    def test_no_wait(self) -> None:
        assert _status_wait_duration({}, False) == 0.0

    def test_default_wait(self) -> None:
        duration = _status_wait_duration({}, True)
        assert duration == STATUS_WAIT_DEFAULT

    def test_explicit_timeout(self) -> None:
        duration = _status_wait_duration({"wait_timeout": 60}, True)
        assert duration == 60.0

    def test_zero_timeout_means_5min(self) -> None:
        """Go: Set to 0 to preserve the original 5-minute timeout."""
        duration = _status_wait_duration({"wait_timeout": 0}, True)
        assert duration == STATUS_WAIT_TIMEOUT
