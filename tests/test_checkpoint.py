"""Tests for orchestration.workflow.checkpoint module."""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from orchestration.workflow.checkpoint import WorkflowCheckpoint
from orchestration.workflow.state import TaskExecution, TaskState


class TestWorkflowCheckpoint:
    """Test WorkflowCheckpoint serialization."""

    def test_create(self):
        cp = WorkflowCheckpoint.create(
            workflow_name="test_wf",
            workflow_id="wf_abc123",
            completed_tasks={},
            task_outputs={},
        )
        assert cp.workflow_name == "test_wf"
        assert cp.workflow_id == "wf_abc123"
        assert cp.checkpoint_id.startswith("cp_")
        assert cp.timestamp > 0
        assert cp.retry_count == 0

    def test_create_with_failed_task(self):
        cp = WorkflowCheckpoint.create(
            workflow_name="test_wf",
            workflow_id="wf_abc",
            completed_tasks={},
            task_outputs={"step1": "done"},
            failed_task="step2",
            failure_reason="API error",
        )
        assert cp.failed_task == "step2"
        assert cp.failure_reason == "API error"
        assert cp.task_outputs == {"step1": "done"}

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "checkpoint.json")

            te = TaskExecution(
                task_name="t1",
                state=TaskState.COMPLETED,
                output="result",
                agent_id="a1",
                elapsed=5.0,
            )
            cp = WorkflowCheckpoint.create(
                workflow_name="wf",
                workflow_id="wf_1",
                completed_tasks={"t1": te},
                task_outputs={"t1": "result"},
                failed_task="t2",
                failure_reason="error",
            )
            cp.retry_count = 1
            cp.save(path)

            assert os.path.exists(path)

            loaded = WorkflowCheckpoint.load(path)
            assert loaded is not None
            assert loaded.workflow_name == "wf"
            assert loaded.workflow_id == "wf_1"
            assert loaded.failed_task == "t2"
            assert loaded.failure_reason == "error"
            assert loaded.retry_count == 1
            assert loaded.task_outputs == {"t1": "result"}
            assert "t1" in loaded.completed_tasks
            assert loaded.completed_tasks["t1"].state == TaskState.COMPLETED
            assert loaded.completed_tasks["t1"].output == "result"

    def test_load_missing_file(self):
        cp = WorkflowCheckpoint.load("/nonexistent/path.json")
        assert cp is None

    def test_save_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = os.path.join(tmpdir, "a", "b", "c")
            path = os.path.join(nested, "checkpoint.json")
            cp = WorkflowCheckpoint.create(
                workflow_name="wf",
                workflow_id="wf_1",
                completed_tasks={},
                task_outputs={},
            )
            cp.save(path)
            assert os.path.exists(path)

    def test_roundtrip_json_structure(self):
        """Verify the JSON structure is human-readable and complete."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cp.json")
            te = TaskExecution(task_name="t1", state=TaskState.FAILED, error="boom")
            cp = WorkflowCheckpoint.create(
                workflow_name="wf",
                workflow_id="wf_1",
                completed_tasks={"t1": te},
                task_outputs={"t1": "partial"},
                failed_task="t1",
                failure_reason="boom",
            )
            cp.retry_count = 2
            cp.save(path)

            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            assert data["workflow_name"] == "wf"
            assert data["workflow_id"] == "wf_1"
            assert data["failed_task"] == "t1"
            assert data["failure_reason"] == "boom"
            assert data["retry_count"] == 2
            assert "checkpoint_id" in data
            assert "timestamp" in data
            assert data["completed_tasks"]["t1"]["state"] == "failed"
            assert data["completed_tasks"]["t1"]["error"] == "boom"
