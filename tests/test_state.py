"""Tests for orchestration.workflow.state module."""
from __future__ import annotations

import pytest

from orchestration.workflow.state import (
    TaskExecution,
    TaskState,
    WorkflowExecution,
    WorkflowState,
)


class TestWorkflowState:
    """Test WorkflowState enum."""

    def test_all_states_exist(self):
        assert WorkflowState.PENDING.value == "pending"
        assert WorkflowState.RUNNING.value == "running"
        assert WorkflowState.PAUSED.value == "paused"
        assert WorkflowState.WAITING_APPROVAL.value == "waiting_approval"
        assert WorkflowState.WAITING_RECOVERY.value == "waiting_recovery"
        assert WorkflowState.COMPLETED.value == "completed"
        assert WorkflowState.FAILED.value == "failed"
        assert WorkflowState.ABORTED.value == "aborted"

    def test_state_count(self):
        assert len(WorkflowState) == 8


class TestTaskState:
    """Test TaskState enum."""

    def test_all_states_exist(self):
        assert TaskState.PENDING.value == "pending"
        assert TaskState.RUNNING.value == "running"
        assert TaskState.WAITING_APPROVAL.value == "waiting_approval"
        assert TaskState.APPROVED.value == "approved"
        assert TaskState.REJECTED.value == "rejected"
        assert TaskState.COMPLETED.value == "completed"
        assert TaskState.FAILED.value == "failed"
        assert TaskState.SKIPPED.value == "skipped"
        assert TaskState.RECOVERED.value == "recovered"

    def test_state_count(self):
        assert len(TaskState) == 9


class TestTaskExecution:
    """Test TaskExecution dataclass."""

    def test_defaults(self):
        te = TaskExecution(task_name="test_task")
        assert te.task_name == "test_task"
        assert te.state == TaskState.PENDING
        assert te.output == ""
        assert te.agent_id == ""
        assert te.elapsed == 0.0
        assert te.error is None
        assert te.retry_count == 0
        assert te.artifacts == []

    def test_to_dict(self):
        te = TaskExecution(
            task_name="t1",
            state=TaskState.COMPLETED,
            output="result",
            agent_id="agent1",
            elapsed=5.0,
            error=None,
            retry_count=1,
            artifacts=["file.py"],
        )
        d = te.to_dict()
        assert d["task_name"] == "t1"
        assert d["state"] == "completed"
        assert d["output"] == "result"
        assert d["agent_id"] == "agent1"
        assert d["elapsed"] == 5.0
        assert d["retry_count"] == 1
        assert d["artifacts"] == ["file.py"]

    def test_from_dict(self):
        d = {
            "task_name": "t1",
            "state": "failed",
            "output": "",
            "agent_id": "a1",
            "elapsed": 3.5,
            "error": "timeout",
            "retry_count": 2,
            "artifacts": [],
        }
        te = TaskExecution.from_dict(d)
        assert te.task_name == "t1"
        assert te.state == TaskState.FAILED
        assert te.error == "timeout"
        assert te.retry_count == 2

    def test_from_dict_defaults(self):
        """Missing fields should use defaults."""
        d = {"task_name": "t1"}
        te = TaskExecution.from_dict(d)
        assert te.state == TaskState.PENDING
        assert te.output == ""
        assert te.retry_count == 0


class TestWorkflowExecution:
    """Test WorkflowExecution dataclass."""

    def test_defaults(self):
        we = WorkflowExecution(workflow_id="wf_123")
        assert we.workflow_id == "wf_123"
        assert we.state == WorkflowState.PENDING
        assert we.task_executions == {}
        assert we.current_task is None
        assert we.total_elapsed == 0.0

    def test_to_dict(self):
        te = TaskExecution(task_name="t1", state=TaskState.COMPLETED)
        we = WorkflowExecution(
            workflow_id="wf_123",
            state=WorkflowState.COMPLETED,
            task_executions={"t1": te},
            current_task="t1",
            total_elapsed=10.0,
            error=None,
        )
        d = we.to_dict()
        assert d["workflow_id"] == "wf_123"
        assert d["state"] == "completed"
        assert d["current_task"] == "t1"
        assert d["total_elapsed"] == 10.0
        assert "t1" in d["task_executions"]
        assert d["task_executions"]["t1"]["state"] == "completed"

    def test_from_dict(self):
        d = {
            "workflow_id": "wf_123",
            "state": "failed",
            "task_executions": {
                "t1": {
                    "task_name": "t1",
                    "state": "failed",
                    "output": "",
                    "agent_id": "a1",
                    "elapsed": 0.0,
                    "error": "boom",
                    "retry_count": 0,
                    "artifacts": [],
                }
            },
            "current_task": "t1",
            "total_elapsed": 5.0,
            "error": "workflow failed",
        }
        we = WorkflowExecution.from_dict(d)
        assert we.workflow_id == "wf_123"
        assert we.state == WorkflowState.FAILED
        assert "t1" in we.task_executions
        assert we.task_executions["t1"].error == "boom"
        assert we.error == "workflow failed"

    def test_from_dict_empty_executions(self):
        d = {"workflow_id": "wf_123", "task_executions": {}}
        we = WorkflowExecution.from_dict(d)
        assert we.task_executions == {}
