"""
验证 v3.0 新增6个功能:
1. 流式输出 streaming
2. 中间结果保存 checkpoint
3. Token预算控制 budget
4. 并行Workflow parallel
5. ContextHub事件持久化 SQLite
6. Task温度控制 temperature
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
import os
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent import Agent, AgentConfig
from core.llm import BaseLLM, LLMResponse, Message, ToolCall, Usage
from core.memory import Conversation
from core.tool import tool, done
from orchestration.context_hub import ContextHub
from orchestration.task import Task
from orchestration.workflow_v2 import TaskNode, WorkflowV2


# ── Mock LLM ─────────────────────────────────────────────────
class MockLLM(BaseLLM):
    def __init__(self, scenario: str = "default"):
        self.scenario = scenario
        self.call_count = 0
        self.temps: list[float | None] = []  # 记录每次调用的温度

    def model_id(self) -> str:
        return "mock"

    def chat(self, messages, tools=None, temperature=None, stream_callback=None):
        self.call_count += 1
        self.temps.append(temperature)

        # 流式回调测试
        if stream_callback:
            stream_callback("Hello ")
            stream_callback("World!")

        if self.scenario == "budget":
            # 每次返回100 tokens，不同observation避免stuck
            return LLMResponse(
                content=f"working {self.call_count}",
                tool_calls=[ToolCall(id=f"c{self.call_count}", function="think", arguments=f'{{"thought": "step{self.call_count}"}}')],
                usage=Usage(prompt_tokens=10, completion_tokens=90, total_tokens=100),
            )

        return LLMResponse(
            content="Done",
            tool_calls=[ToolCall(id="cf", function="done", arguments='{"result": "ok"}')],
            usage=Usage(5, 5, 10),
        )


# ── 测试工具 ────────────────────────────────────────────────
@tool
def think(thought: str) -> str:
    """Think."""
    return thought


# ── 6个新功能测试 ──────────────────────────────────────────

def test_streaming():
    """测试1: 流式输出"""
    print("\n[TEST] Streaming Output")
    llm = MockLLM()
    agent = Agent(llm=llm, tools=[think, done], config=AgentConfig(max_iterations=3))

    tokens = []
    def on_token(t):
        tokens.append(t)

    result = agent.run("Test", stream_callback=on_token)

    assert tokens == ["Hello ", "World!"], f"Expected streaming tokens, got: {tokens}"
    print(f"  Streamed tokens: {tokens}")
    print("  PASSED")


def test_checkpoint():
    """测试2: 中间结果保存"""
    print("\n[TEST] Step-level Checkpoint")
    ckpt_dir = str(Path(tempfile.gettempdir()) / 'agent_workflow')
    os.makedirs(ckpt_dir, exist_ok=True)

    llm = MockLLM("budget")
    agent = Agent(
        llm=llm,
        tools=[think, done],
        config=AgentConfig(
            max_iterations=5,
            checkpoint_enabled=True,
            checkpoint_dir=ckpt_dir,
        ),
    )

    result = agent.run("Test")

    # 应该有checkpoint文件
    ckpt_files = [f for f in os.listdir(ckpt_dir) if f.startswith("ckpt_")]
    assert len(ckpt_files) > 0, "No checkpoint files created"

    # 验证checkpoint内容
    with open(os.path.join(ckpt_dir, ckpt_files[0])) as f:
        ckpt = json.load(f)
    assert "step" in ckpt and "timestamp" in ckpt

    print(f"  Checkpoint files: {len(ckpt_files)}")
    print(f"  First checkpoint: step={ckpt['step']}, tokens={ckpt['total_tokens']}")
    print("  PASSED")

    # 清理
    for f in ckpt_files:
        os.remove(os.path.join(ckpt_dir, f))


def test_budget():
    """测试3: Token预算控制"""
    print("\n[TEST] Token Budget Control")
    llm = MockLLM("budget")
    agent = Agent(
        llm=llm,
        tools=[think, done],
        config=AgentConfig(
            max_iterations=10,
            budget_tokens=150,  # 最多150 tokens (Mock每次100)
        ),
    )

    result = agent.run("Test")

    # 应该因为budget而提前停止
    assert "budget" in (result.stop_reason or ""), f"Expected budget stop, got: {result.stop_reason}"
    # Mock每次100 tokens，150 budget在第2次(200 tokens)超出
    assert result.iterations <= 3, f"Expected <=3 iterations, got: {result.iterations}"

    print(f"  Iterations: {result.iterations}")
    print(f"  Stop reason: {result.stop_reason}")
    print("  PASSED")


def test_parallel_workflow():
    """测试4: 并行Workflow"""
    print("\n[TEST] Parallel Workflow Execution")

    llm = MockLLM()
    agent = Agent(llm=llm, tools=[done], config=AgentConfig(max_iterations=3))

    wf = WorkflowV2("parallel_test", auto_recover=True)
    wf.register_agent("agent", agent)

    # 添加3个可以并行的Task
    wf.add_task(TaskNode(Task(name="task_a", description="Task A"), agent_id="agent", parallel=True))
    wf.add_task(TaskNode(Task(name="task_b", description="Task B"), agent_id="agent", parallel=True))
    wf.add_task(TaskNode(Task(name="task_c", description="Task C"), agent_id="agent"))  # 不并行

    result = wf.run_parallel(max_workers=2)

    success = sum(1 for t in result.task_executions.values() if t.state.value in ("completed", "recovered"))
    print(f"  Success: {success}/{len(result.task_executions)}")
    print(f"  Elapsed: {result.total_elapsed:.2f}s")
    print("  PASSED")


def test_event_persistence():
    """测试5: ContextHub事件持久化"""
    print("\n[TEST] ContextHub Event Persistence (SQLite)")

    db_path = str(Path(tempfile.gettempdir()) / 'agent_workflow')
    if os.path.exists(db_path):
        os.remove(db_path)

    hub = ContextHub(db_path=db_path)
    conv = hub.register("test_agent", "You are a test")
    conv.add_user("Hello")
    conv.add_assistant("Hi there")

    # 查询事件
    events = hub.query_events(limit=10)
    assert len(events) >= 2, f"Expected >=2 events, got: {len(events)}"

    # 按类型查询
    msg_events = hub.query_events(event_type="message_added")
    assert len(msg_events) >= 1

    # 统计
    stats = hub.get_event_stats()
    assert stats["total_events"] >= 2

    print(f"  Total events persisted: {stats['total_events']}")
    print(f"  Event types: {list(stats['by_type'].keys())}")
    print("  PASSED")

    os.remove(db_path)


def test_temperature_control():
    """测试6: Task温度控制"""
    print("\n[TEST] Task Temperature Control")

    llm = MockLLM()
    agent = Agent(llm=llm, tools=[done], config=AgentConfig(max_iterations=3, temperature=0.5))

    wf = WorkflowV2("temp_test", auto_recover=True)
    wf.register_agent("agent", agent)

    # Task A: 默认温度(0.5)
    wf.add_task(TaskNode(Task(name="task_default", description="Default temp"), agent_id="agent"))
    # Task B: 高温(1.5)
    wf.add_task(TaskNode(Task(name="task_hot", description="Hot temp"), agent_id="agent", temperature=1.5))
    # Task C: 低温(0.1)
    wf.add_task(TaskNode(Task(name="task_cold", description="Cold temp"), agent_id="agent", temperature=0.1))

    result = wf.run()

    # 检查温度记录
    assert 0.5 in llm.temps, f"Expected 0.5 in temps, got: {llm.temps}"
    assert 1.5 in llm.temps, f"Expected 1.5 in temps, got: {llm.temps}"
    assert 0.1 in llm.temps, f"Expected 0.1 in temps, got: {llm.temps}"

    print(f"  Temperatures used: {llm.temps}")
    print("  PASSED")


# ── 主入口 ──────────────────────────────────────────────────

TESTS = [
    test_streaming,
    test_checkpoint,
    test_budget,
    test_parallel_workflow,
    test_event_persistence,
    test_temperature_control,
]

if __name__ == "__main__":
    print("=" * 60)
    print("Agent Workflow Framework v3.0 — New Features Verification")
    print("=" * 60)

    passed = 0
    failed = 0
    for test_fn in TESTS:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  FAILED: {e}")
            import traceback
            traceback.print_exc()

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed, {len(TESTS)} total")
    print("=" * 60)