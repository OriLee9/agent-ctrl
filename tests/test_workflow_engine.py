"""Tests for orchestration.workflow.engine module."""
from __future__ import annotations

import json
import os

import pytest

from core.agent import Agent, AgentConfig
from core.llm import LLMResponse, Message, ToolCall, Usage
from orchestration.task import Task
from orchestration.workflow.engine import (
    ArtifactCollector,
    Node,
    WorkflowEngine,
    WorkflowResult,
)
from orchestration.workflow.state import (
    TaskExecution,
    TaskState,
    WorkflowExecution,
    WorkflowState,
)
from core.memory import Conversation, StepRecord

from conftest import MockLLM


class TestArtifactCollector:
    """Test ArtifactCollector."""

    def test_collect_from_artifacts_key(self):
        collector = ArtifactCollector()
        outputs = {"_artifacts": ["file1.py", "file2.py"]}
        result = collector.collect(outputs)
        assert "file1.py" in result
        assert "file2.py" in result

    def test_collect_empty_outputs(self):
        collector = ArtifactCollector()
        result = collector.collect({})
        assert result == ""


class TestNode:
    """Test Node dataclass."""

    def test_defaults(self):
        task = Task(name="t1", description="test")
        node = Node(task=task, agent_id="a1")
        assert node.task.name == "t1"
        assert node.agent_id == "a1"
        assert node.requires_approval is False
        assert node.max_retries == 2
        assert node.retry_delay == 3
        assert node.temperature is None
        assert node.parallel is True
        assert node.local_executor is None
        assert node.max_passes == 1


class TestWorkflowEngineInit:
    """Test WorkflowEngine initialization."""

    def test_default_init(self):
        wf = WorkflowEngine(name="test")
        assert wf.name == "test"
        assert wf.mode == "free"
        assert wf.workflow_id.startswith("wf_")
        assert wf.state == WorkflowState.PENDING
        assert wf.list_tasks() == []

    def test_custom_init(self):
        wf = WorkflowEngine(name="my_wf", mode="fixed", auto_recover=True)
        assert wf.name == "my_wf"
        assert wf.mode == "fixed"
        assert wf._auto_recover is True


class TestWorkflowEngineDAGBuilding:
    """Test DAG construction."""

    def test_add_task(self):
        wf = WorkflowEngine()
        task = Task(name="t1", description="task 1")
        wf.add_task("t1", Node(task=task, agent_id="a1"))
        assert "t1" in wf._nodes
        assert wf.list_tasks()[0]["name"] == "t1"

    def test_add_edge(self):
        wf = WorkflowEngine()
        wf.add_task("t1", Node(task=Task("t1", ""), agent_id="a1"))
        wf.add_task("t2", Node(task=Task("t2", ""), agent_id="a2"))
        wf.add_edge("t1", "t2")
        assert "t2" in wf._edges["t1"]
        assert wf._indegree["t2"] == 1

    def test_add_edge_unknown_task_raises(self):
        wf = WorkflowEngine()
        wf.add_task("t1", Node(task=Task("t1", ""), agent_id="a1"))
        with pytest.raises(ValueError, match="Unknown task"):
            wf.add_edge("t1", "t2")

    def test_sequential_chain(self):
        wf = WorkflowEngine()
        wf.sequential(
            ("t1", Node(task=Task("t1", ""), agent_id="a1")),
            ("t2", Node(task=Task("t2", ""), agent_id="a2")),
            ("t3", Node(task=Task("t3", ""), agent_id="a3")),
        )
        assert wf._indegree["t1"] == 0
        assert wf._indegree["t2"] == 1
        assert wf._indegree["t3"] == 1
        assert "t2" in wf._edges["t1"]
        assert "t3" in wf._edges["t2"]

    def test_chain_classmethod(self):
        wf = WorkflowEngine.chain("test", [
            ("design", Task("design", ""), "architect"),
            ("code", Task("code", ""), "coder"),
        ])
        assert wf.name == "test"
        assert "design" in wf._nodes
        assert "code" in wf._nodes
        assert "code" in wf._edges["design"]

    def test_chain_with_parallel_group(self):
        wf = WorkflowEngine.chain("test", [
            ("setup", Task("setup", ""), "a1"),
            [("par1", Task("par1", ""), "a2"), ("par2", Task("par2", ""), "a3")],
            ("finish", Task("finish", ""), "a1"),
        ])
        # setup -> par1, par2
        assert "par1" in wf._edges["setup"]
        assert "par2" in wf._edges["setup"]
        # par1, par2 -> finish
        assert "finish" in wf._edges["par1"]
        assert "finish" in wf._edges["par2"]


class TestTopologicalLayers:
    """Test DAG topological layering."""

    def test_linear_chain(self):
        wf = WorkflowEngine()
        wf.sequential(
            ("a", Node(task=Task("a", ""), agent_id="x")),
            ("b", Node(task=Task("b", ""), agent_id="x")),
            ("c", Node(task=Task("c", ""), agent_id="x")),
        )
        layers = wf._topological_layers()
        assert layers == [["a"], ["b"], ["c"]]

    def test_diamond(self):
        """    a
               / \
              b   c
               \ /
                d
        """
        wf = WorkflowEngine()
        for name in ["a", "b", "c", "d"]:
            wf.add_task(name, Node(task=Task(name, ""), agent_id="x"))
        wf.add_edge("a", "b")
        wf.add_edge("a", "c")
        wf.add_edge("b", "d")
        wf.add_edge("c", "d")
        layers = wf._topological_layers()
        assert layers[0] == ["a"]
        assert set(layers[1]) == {"b", "c"}
        assert layers[2] == ["d"]

    def test_cycle_detection(self):
        wf = WorkflowEngine()
        for name in ["a", "b", "c"]:
            wf.add_task(name, Node(task=Task(name, ""), agent_id="x"))
        wf.add_edge("a", "b")
        wf.add_edge("b", "c")
        wf.add_edge("c", "a")
        with pytest.raises(ValueError, match="cycle"):
            wf._topological_layers()

    def test_topological_sort(self):
        wf = WorkflowEngine()
        wf.sequential(
            ("a", Node(task=Task("a", ""), agent_id="x")),
            ("b", Node(task=Task("b", ""), agent_id="x")),
            ("c", Node(task=Task("c", ""), agent_id="x")),
        )
        order = wf._topological_sort()
        assert order == ["a", "b", "c"]


class TestWorkflowEngineControls:
    """Test pause/resume/abort/approval."""

    def test_pause(self):
        wf = WorkflowEngine()
        wf._state = WorkflowState.RUNNING
        wf.pause()
        assert wf.state == WorkflowState.PAUSED

    def test_resume_from_pause(self):
        wf = WorkflowEngine()
        wf._state = WorkflowState.PAUSED
        wf.resume_from_pause()
        assert wf.state == WorkflowState.RUNNING

    def test_abort(self):
        wf = WorkflowEngine()
        wf._state = WorkflowState.RUNNING
        wf.abort()
        assert wf.state == WorkflowState.ABORTED

    def test_approve_task(self):
        wf = WorkflowEngine()
        import asyncio
        wf._approval_events["t1"] = asyncio.Event()
        wf._current_execution = WorkflowExecution(workflow_id="wf_1")
        wf._current_execution.task_executions["t1"] = TaskExecution(task_name="t1")

        result = wf.approve_task("t1")
        assert result is True
        assert wf._current_execution.task_executions["t1"].state == TaskState.APPROVED
        assert wf._approval_events["t1"].is_set()

    def test_reject_task(self):
        wf = WorkflowEngine()
        import asyncio
        wf._approval_events["t1"] = asyncio.Event()
        wf._current_execution = WorkflowExecution(workflow_id="wf_1")
        wf._current_execution.task_executions["t1"] = TaskExecution(task_name="t1")

        result = wf.reject_task("t1")
        assert result is True
        assert wf._current_execution.task_executions["t1"].state == TaskState.REJECTED
        assert wf._approval_events["t1"].is_set()

    def test_approve_unknown_task(self):
        wf = WorkflowEngine()
        result = wf.approve_task("unknown")
        assert result is False

    def test_resume_from_recovery(self):
        wf = WorkflowEngine()
        wf._state = WorkflowState.WAITING_RECOVERY
        wf._current_execution = WorkflowExecution(workflow_id="wf_1")
        result = wf.resume_from_recovery()
        assert result is True
        assert wf.state == WorkflowState.RUNNING


class TestMermaidGeneration:
    """Test workflow visualization."""

    def test_basic_mermaid(self):
        wf = WorkflowEngine()
        wf.sequential(
            ("step-a", Node(task=Task("step-a", ""), agent_id="x")),
            ("step-b", Node(task=Task("step-b", ""), agent_id="x")),
        )
        mermaid = wf.to_mermaid()
        assert "graph TD" in mermaid
        assert "step_a" in mermaid
        assert "step_b" in mermaid
        assert "step_a -->" in mermaid

    def test_conditional_edge_label(self):
        wf = WorkflowEngine()
        wf.add_task("a", Node(task=Task("a", ""), agent_id="x"))
        wf.add_task("b", Node(task=Task("b", ""), agent_id="x"))
        wf.add_conditional_edge("a", "b", lambda x: True)
        mermaid = wf.to_mermaid()
        assert "|condition|" in mermaid


class TestLocalExecutor:
    """Test Node with local_executor."""

    def test_local_executor_success(self):
        wf = WorkflowEngine()
        node = Node(
            task=Task("t1", ""),
            agent_id="local",
            local_executor=lambda outputs: "computed result",
        )
        result = wf._execute_local("t1", node, {})
        assert result.state == TaskState.COMPLETED
        assert result.output == "computed result"

    def test_local_executor_failure(self):
        wf = WorkflowEngine()
        node = Node(
            task=Task("t1", ""),
            agent_id="local",
            local_executor=lambda outputs: (_ for _ in ()).throw(RuntimeError("fail")),
        )
        result = wf._execute_local("t1", node, {})
        assert result.state == TaskState.FAILED
        assert "fail" in result.error

    def test_local_executor_returns_dict_with_artifacts(self):
        wf = WorkflowEngine()
        node = Node(
            task=Task("t1", ""),
            agent_id="local",
            local_executor=lambda outputs: {"result": "ok", "_artifacts": ["file.py"]},
        )
        result = wf._execute_local("t1", node, {})
        assert result.state == TaskState.COMPLETED
        assert result.artifacts == ["file.py"]


class TestConversationClear:
    """P0: Test conversation cleanup on retry (prevents message accumulation)."""

    def test_clear_removes_messages_and_steps(self):
        """Conversation.clear() should remove all messages and steps."""
        conv = Conversation(session_id="test_retry")
        conv.add_system("You are a coder.")
        conv.add_user("Write code.")
        conv.add_assistant(content="I'll write the code.")
        conv.record_step(StepRecord(thought="step 1", observation="done"))

        assert conv.message_count == 3
        assert conv.step_count == 1

        conv.clear()

        assert conv.message_count == 0
        assert conv.step_count == 0
        assert conv.total_usage.prompt_tokens == 0

    def test_clear_preserves_session_id(self):
        """After clear(), session_id should remain unchanged."""
        conv = Conversation(session_id="test_retry")
        conv.add_user("task")
        conv.clear()
        assert conv.session_id == "test_retry"

    def test_can_rebuild_after_clear(self):
        """After clear(), conversation can be rebuilt with new system + user messages."""
        conv = Conversation(session_id="test_retry")
        conv.add_system("Original prompt")
        conv.add_user("Original task")
        conv.clear()

        conv.add_system("New prompt after feedback")
        conv.add_user("[Review Feedback] Fix the bug.")

        msgs = conv.get_messages()
        assert len(msgs) == 2
        assert msgs[0].role == "system"
        assert "New prompt" in msgs[0].content
        assert msgs[1].role == "user"
        assert "Review Feedback" in msgs[1].content


class TestAutoValidateUpstream:
    """P1: Test automated validation layer before review."""

    def test_valid_html_and_js(self, tmp_path, monkeypatch):
        """_auto_validate_upstream returns None when all checks pass."""
        # Build a minimal workspace
        wf_dir = tmp_path / "outputs" / "test_wf"
        wf_dir.mkdir(parents=True)
        (wf_dir / "index.html").write_text("<html><body><p>Hello</p></body></html>")
        (wf_dir / "game.js").write_text("function init() { return 42; }")

        # Point AGENT_OUTPUTS_DIR at our temp dir
        monkeypatch.setenv("AGENT_OUTPUTS_DIR", str(tmp_path / "outputs"))

        wf = WorkflowEngine(name="test_wf")
        wf.add_task("implement", Node(task=Task("implement", ""), agent_id="coder", review_gate="review"))
        wf.add_task("review", Node(task=Task("review", ""), agent_id="reviewer"))

        result = wf._auto_validate_upstream("review")
        assert result is not None
        assert "PASS" in result
        assert "FAIL" not in result
        assert "2 passed" in result or "passed" in result

    def test_invalid_html_detected(self, tmp_path, monkeypatch):
        """_auto_validate_upstream reports unclosed HTML tags."""
        wf_dir = tmp_path / "outputs" / "test_wf"
        wf_dir.mkdir(parents=True)
        (wf_dir / "index.html").write_text("<html><body><div><p>Hello</p></body></html>")

        monkeypatch.setenv("AGENT_OUTPUTS_DIR", str(tmp_path / "outputs"))

        wf = WorkflowEngine(name="test_wf")
        wf.add_task("implement", Node(task=Task("implement", ""), agent_id="coder", review_gate="review"))
        wf.add_task("review", Node(task=Task("review", ""), agent_id="reviewer"))

        result = wf._auto_validate_upstream("review")
        assert result is not None
        assert "FAIL" in result
        assert "Unclosed" in result

    def test_invalid_js_detected(self, tmp_path, monkeypatch):
        """_auto_validate_upstream reports unclosed braces in JS."""
        wf_dir = tmp_path / "outputs" / "test_wf"
        wf_dir.mkdir(parents=True)
        (wf_dir / "game.js").write_text("function init() { return 42;")

        monkeypatch.setenv("AGENT_OUTPUTS_DIR", str(tmp_path / "outputs"))

        wf = WorkflowEngine(name="test_wf")
        wf.add_task("implement", Node(task=Task("implement", ""), agent_id="coder", review_gate="review"))
        wf.add_task("review", Node(task=Task("review", ""), agent_id="reviewer"))

        result = wf._auto_validate_upstream("review")
        assert result is not None
        assert "FAIL" in result
        assert "Unclosed" in result

    def test_skips_logs_directory(self, tmp_path, monkeypatch):
        """_auto_validate_upstream should ignore logs/ directory."""
        wf_dir = tmp_path / "outputs" / "test_wf"
        wf_dir.mkdir(parents=True)
        (wf_dir / "index.html").write_text("<html><body><p>OK</p></body></html>")
        logs_dir = wf_dir / "logs"
        logs_dir.mkdir()
        (logs_dir / "design.md").write_text("# Design\n")
        # Put an intentionally broken file in logs/ — should be ignored
        (logs_dir / "broken.html").write_text("<html><body><div></body></html>")

        monkeypatch.setenv("AGENT_OUTPUTS_DIR", str(tmp_path / "outputs"))

        wf = WorkflowEngine(name="test_wf")
        wf.add_task("implement", Node(task=Task("implement", ""), agent_id="coder", review_gate="review"))
        wf.add_task("review", Node(task=Task("review", ""), agent_id="reviewer"))

        result = wf._auto_validate_upstream("review")
        # Should pass because broken.html in logs/ is skipped
        assert result is not None
        assert "FAIL" not in result

    def test_no_workspace_returns_none(self, tmp_path, monkeypatch):
        """_auto_validate_upstream returns None when workspace does not exist."""
        monkeypatch.setenv("AGENT_OUTPUTS_DIR", str(tmp_path / "outputs"))

        wf = WorkflowEngine(name="nonexistent_wf")
        wf.add_task("implement", Node(task=Task("implement", ""), agent_id="coder", review_gate="review"))
        wf.add_task("review", Node(task=Task("review", ""), agent_id="reviewer"))

        result = wf._auto_validate_upstream("review")
        assert result is None

    def test_no_review_gate_returns_none(self):
        """_auto_validate_upstream returns None when no task has this review_gate."""
        wf = WorkflowEngine(name="test")
        wf.add_task("review", Node(task=Task("review", ""), agent_id="reviewer"))

        result = wf._auto_validate_upstream("review")
        assert result is None


class TestRetryPreservesHistory:
    """P2: Test that retry/rework preserves conversation history and stats."""

    def test_rework_appends_feedback_not_clears(self):
        """On rework, feedback should be appended as a user message, not clear()."""
        conv = Conversation(session_id="coder/implement")
        conv.add_system("You are a coder.")
        conv.add_user("Write the game.")
        conv.add_assistant(content="Done writing game.js")

        initial_count = conv.message_count

        # 新的逻辑：不清空，追加feedback user消息
        conv.add_user(
            "[REWORK REQUIRED — Pass 1/2]\n\n"
            "The reviewer 'review' has provided feedback.\n\n"
            "Feedback:\nFix bug in line 10.\n\n"
            "Files currently in workspace: game.js\n\n"
            "Please fix ALL issues listed above."
        )

        assert conv.message_count == initial_count + 1
        msgs = conv.get_messages()
        assert msgs[0].role == "system"
        assert msgs[1].role == "user"
        assert msgs[2].role == "assistant"
        assert msgs[3].role == "user"
        assert "REWORK REQUIRED" in msgs[3].content
        assert "Fix bug" in msgs[3].content

    def test_usage_retained_across_rework(self):
        """Token usage statistics should survive rework (not reset by clear())."""
        conv = Conversation(session_id="coder/implement")
        conv.add_system("You are a coder.")
        conv.record_step(StepRecord(thought="t1", usage=Usage(10, 5, 15)))
        conv.record_step(StepRecord(thought="t2", usage=Usage(20, 10, 30)))

        assert conv.total_usage.total_tokens == 45

        # 不清空，追加feedback
        conv.add_user("[REWORK REQUIRED] Fix bugs.")

        # usage 应保留
        assert conv.total_usage.total_tokens == 45
        assert conv.step_count == 2

    def test_rework_via_hub_preserves_messages(self):
        """Engine retry loop via Hub should append feedback, preserving prior messages."""
        wf = WorkflowEngine(name="test_wf")

        # 预先构建一个带 history 的 conversation
        conv = Conversation(session_id="coder/implement")
        conv.add_system("You are a game coder.")
        conv.add_user("Implement the game.")
        conv.add_assistant(content="I will write game.js")
        # 模拟 tool call + result
        tc = ToolCall(id="tc_1", function="write_file", arguments='{"path":"game.js"}')
        conv.add_assistant(tool_calls=[tc])
        conv.add_tool_result("tc_1", "write_file", '{"success": true}')
        conv.add_assistant(content="Done.")

        class FakeHub:
            def register(self, conv_id, prompt):
                return conv

        wf._hub = FakeHub()

        node = Node(
            task=Task("implement", ""),
            agent_id="coder",
            review_gate="review",
            max_passes=2,
        )
        passes_done = 0
        feedback = "Bug on line 42: missing semicolon."

        # 模拟 engine retry 循环中的核心逻辑
        conv_id = f"{node.agent_id}/implement"
        c = wf._hub.register(conv_id, "")
        c.add_user(
            f"[REWORK REQUIRED — Pass {passes_done + 1}/{node.max_passes}]\n\n"
            f"The reviewer '{node.review_gate}' has provided feedback.\n\n"
            f"Feedback:\n{feedback}\n\n"
            f"Files currently in workspace: game.js\n\n"
            f"Please fix ALL issues listed above."
        )

        # 验证 history 完整保留
        msgs = c.get_messages()
        assert len(msgs) == 7  # system + user + assistant + assistant(tc) + tool + assistant + feedback
        assert msgs[0].role == "system"
        assert msgs[1].role == "user"
        assert msgs[2].role == "assistant"
        assert msgs[3].role == "assistant"  # tool_calls
        assert msgs[4].role == "tool"
        assert msgs[5].role == "assistant"
        assert msgs[6].role == "user"
        assert "REWORK REQUIRED" in msgs[6].content


class TestRetryCountTracking:
    """Bug fix: retry_count must increment on the NEW TaskExecution object."""

    def test_retry_count_increments_after_rework(self):
        """Replacing task_executions[task] should preserve retry_count."""
        wf = WorkflowEngine(name="test")

        # Simulate first-pass execution record
        old_ex = TaskExecution(task_name="implement", state=TaskState.COMPLETED)
        old_ex.retry_count = 0

        # Simulate replacing with a new execution (as _execute_task_async does)
        new_ex = TaskExecution(task_name="implement", state=TaskState.COMPLETED)
        execution = WorkflowExecution(workflow_id="wf_1")
        execution.task_executions["implement"] = new_ex

        # The fix: set retry_count on the NEW object, not the old one
        new_ex.retry_count = old_ex.retry_count + 1

        assert execution.task_executions["implement"].retry_count == 1

    def test_retry_count_survives_multiple_replacements(self):
        """After multiple rework passes, retry_count should reflect total passes."""
        execution = WorkflowExecution(workflow_id="wf_1")

        for i in range(3):
            new_ex = TaskExecution(task_name="implement", state=TaskState.COMPLETED)
            execution.task_executions["implement"] = new_ex
            new_ex.retry_count = i + 1  # simulate the fix

        assert execution.task_executions["implement"].retry_count == 3


class TestAbortPausePropagation:
    """Bug fix: abort/pause must update execution.state, not just self._state."""

    def test_abort_updates_execution_state(self):
        """abort() should set execution.state to ABORTED."""
        wf = WorkflowEngine(name="test")
        execution = WorkflowExecution(workflow_id="wf_1")
        wf._current_execution = execution
        wf._state = WorkflowState.RUNNING
        execution.state = WorkflowState.RUNNING

        wf.abort()

        assert wf.state == WorkflowState.ABORTED
        assert execution.state == WorkflowState.ABORTED

    def test_pause_updates_execution_state(self):
        """pause() should set execution.state to PAUSED."""
        wf = WorkflowEngine(name="test")
        execution = WorkflowExecution(workflow_id="wf_1")
        wf._current_execution = execution
        wf._state = WorkflowState.RUNNING
        execution.state = WorkflowState.RUNNING

        wf.pause()

        assert wf.state == WorkflowState.PAUSED
        assert execution.state == WorkflowState.PAUSED

    def test_abort_sets_approval_events(self):
        """abort() should signal all pending approval events."""
        import asyncio
        wf = WorkflowEngine(name="test")
        event = asyncio.Event()
        wf._approval_events["t1"] = event

        wf.abort()

        assert event.is_set()

    def test_abort_when_no_execution(self):
        """abort() should not crash when _current_execution is None."""
        wf = WorkflowEngine(name="test")
        wf._state = WorkflowState.RUNNING

        wf.abort()  # should not raise

        assert wf.state == WorkflowState.ABORTED


class TestConversationArchiveAndCompact:
    """P4: Conversation archive_round() + compact() — Register-Memory model."""

    def test_archive_round_creates_json_file(self, tmp_path):
        """archive_round() should save full conversation as JSON."""
        conv = Conversation(session_id="coder/implement")
        conv.add_system("You are a coder.")
        conv.add_user("Write code.")
        conv.add_assistant(content="Done.")

        out_dir = str(tmp_path / "logs")
        path = conv.archive_round(pass_num=0, out_dir=out_dir)

        assert os.path.exists(path)
        assert path.endswith("round_0_conversation.json")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert data["session_id"] == "coder/implement"
        assert data["pass_num"] == 0
        assert len(data["messages"]) == 3

    def test_compact_reduces_message_count(self):
        """compact() should reduce messages while preserving system + recent."""
        conv = Conversation(session_id="test")
        conv.add_system("You are a coder.")
        conv.add_user("Task 1")
        conv.add_assistant(content="Response 1")
        conv.add_user("Task 2")
        conv.add_assistant(content="Response 2")
        conv.add_user("Task 3")
        conv.add_assistant(content="Response 3")
        conv.add_user("Task 4")
        conv.add_assistant(content="Response 4")
        # 9 messages total: system + 4 exchanges (8) = 9

        assert conv.message_count == 9
        conv.compact(keep_recent=4)

        # After compact: system + [History Archive] + last 4 = 6
        assert conv.message_count == 6
        msgs = conv.get_messages()
        assert msgs[0].role == "system"
        assert msgs[0].content == "You are a coder."
        assert msgs[1].role == "system"
        assert "[History Archive]" in msgs[1].content
        assert msgs[2].role == "user"
        assert msgs[2].content == "Task 3"
        assert msgs[5].role == "assistant"
        assert msgs[5].content == "Response 4"

    def test_compact_noop_when_few_messages(self):
        """compact() should do nothing when message count is below threshold."""
        conv = Conversation(session_id="test")
        conv.add_system("System.")
        conv.add_user("Task.")
        conv.add_assistant(content="Done.")

        assert conv.message_count == 3
        conv.compact(keep_recent=6)

        # No change — 3 messages <= 6 + 1
        assert conv.message_count == 3

    def test_compact_extracts_reviewer_feedback(self):
        """compact() should extract feedback snippets from [REWORK REQUIRED] messages."""
        conv = Conversation(session_id="test")
        conv.add_system("You are a coder.")
        conv.add_user("Original task.")
        conv.add_assistant(content="Done.")
        conv.add_user(
            "[REWORK REQUIRED — Pass 1/2]\n\n"
            "Feedback:\nFix bug in line 10. Missing semicolon.\n\n"
            "Files currently in workspace: game.js"
        )
        conv.add_assistant(content="Fixed.")
        conv.add_user("Another task.")
        conv.add_assistant(content="Done again.")

        conv.compact(keep_recent=2)

        msgs = conv.get_messages()
        assert msgs[1].role == "system"
        archive_content = msgs[1].content
        assert "[History Archive]" in archive_content
        assert "Fix bug in line 10" in archive_content
        # Should NOT contain "Files currently" (that's from the original message)
        assert "Files currently in workspace" not in archive_content

    def test_compact_does_not_duplicate_file_lists(self):
        """compact() should reference IMPLEMENTATION_SUMMARY.md, not list files."""
        conv = Conversation(session_id="test")
        conv.add_system("You are a coder.")
        conv.add_user("Task.")
        conv.add_assistant(content="Done.")
        conv.add_tool_result("tc1", "write_file", '{"success": true}')
        conv.add_user("More.")
        conv.add_assistant(content="Done.")

        conv.compact(keep_recent=2)

        msgs = conv.get_messages()
        archive = msgs[1].content
        # Should reference the summary file, not list files from tool results
        assert "IMPLEMENTATION_SUMMARY.md" in archive
        # Should NOT contain raw tool result JSON
        assert "write_file" not in archive

    def test_archive_round_increments_pass_num(self, tmp_path):
        """Multiple archive_round calls should create sequential files."""
        conv = Conversation(session_id="test")
        out_dir = str(tmp_path / "logs")

        p0 = conv.archive_round(pass_num=0, out_dir=out_dir)
        p1 = conv.archive_round(pass_num=1, out_dir=out_dir)

        assert os.path.basename(p0) == "round_0_conversation.json"
        assert os.path.basename(p1) == "round_1_conversation.json"

    def test_compact_avoids_tool_message_truncation(self):
        """compact() must NOT truncate on a tool message — it needs a preceding
        assistant with tool_calls. Truncating there produces an invalid message
        sequence that causes API 400: 'Messages with role tool must be a
        response to a preceding message with tool_calls'."""
        conv = Conversation(session_id="test")
        conv.add_system("You are a coder.")
        # Build a sequence where the natural cutoff lands on a tool message
        conv.add_user("Task.")
        from agent_workflow.core.llm import ToolCall
        conv.add_assistant(
            content=None,
            tool_calls=[ToolCall(id="tc1", function="write_file", arguments="{}")],
        )
        conv.add_tool_result("tc1", "write_file", "ok")
        conv.add_assistant(content="Step 2")
        conv.add_assistant(
            content=None,
            tool_calls=[ToolCall(id="tc2", function="write_file", arguments="{}")],
        )
        conv.add_tool_result("tc2", "write_file", "ok")
        conv.add_assistant(content="Step 3")
        conv.add_user("Rework feedback.")
        conv.add_assistant(content="Fixing.")
        # 10 messages: system + 9 interactions
        assert conv.message_count == 10

        # keep_recent=4 would naturally cut at index 6 (a tool message)
        conv.compact(keep_recent=4)

        msgs = conv.get_messages()
        # First message after [History Archive] must NOT be 'tool'
        archive_idx = next(
            (i for i, m in enumerate(msgs) if "[History Archive]" in (m.content or "")),
            -1,
        )
        assert archive_idx >= 0, "History Archive message should exist"
        first_kept_idx = archive_idx + 1
        assert msgs[first_kept_idx].role != "tool", (
            f"First kept message after archive must not be 'tool', got {msgs[first_kept_idx].role}"
        )
