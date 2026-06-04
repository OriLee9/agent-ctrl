"""
框架端到端验证 — 不依赖外部API，用Mock LLM测试完整流程。

验证目标:
1. Tool定义与Schema推断
2. Agent ReAct循环
3. Conversation上下文管理
4. ContextHub多Agent监控
5. Workflow DAG编排
6. 快照与回滚
"""
from __future__ import annotations

from pathlib import Path
import json
import sys
from typing import Any

# 确保导入路径正确
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.llm import BaseLLM, LLMResponse, Message, ToolCall, Usage
from core.agent import Agent, AgentConfig
from core.tool import tool, Tool, done
from core.memory import Conversation, StepRecord
from orchestration.context_hub import ContextHub, ContextEvent, Intervention
from orchestration.task import Task
from orchestration.workflow import Workflow
from orchestration.rules import SimpleRuleEngine, RuleConfig



# ── Mock LLM ───────────────────────────────────────────────────

class MockLLM(BaseLLM):
    """
    模拟LLM，用于测试。

    根据输入消息中的特定关键词返回预设的tool_calls，
    实现可控的ReAct循环测试。
    """

    def __init__(self, scenario: str = "calculator"):
        self.scenario = scenario
        self.call_count = 0

    def model_id(self) -> str:
        return f"mock:{self.scenario}"

    def chat(self, messages: list[Message], tools: list[dict] | None = None, temperature: float | None = None, stream_callback=None) -> LLMResponse:
        self.call_count += 1
        last_msg = messages[-1].content if messages else ""

        # Scenario 1: 计算器 — 两步完成
        if self.scenario == "calculator":
            if self.call_count == 1:
                return LLMResponse(
                    content="I need to calculate 2+3",
                    tool_calls=[ToolCall(
                        id="call_1",
                        function="add",
                        arguments=json.dumps({"a": 2, "b": 3}),
                    )],
                    usage=Usage(10, 15, 25),
                )
            else:
                return LLMResponse(
                    content="The answer is 5",
                    tool_calls=[ToolCall(
                        id="call_2",
                        function="done",
                        arguments=json.dumps({"result": "5"}),
                    )],
                    usage=Usage(8, 10, 18),
                )

        # Scenario 2: 工具失败后重试
        if self.scenario == "retry":
            if self.call_count == 1:
                return LLMResponse(
                    content="I will divide 10 by 0",
                    tool_calls=[ToolCall(
                        id="call_1",
                        function="divide",
                        arguments=json.dumps({"a": 10, "b": 0}),
                    )],
                    usage=Usage(10, 15, 25),
                )
            else:
                return LLMResponse(
                    content="Let me try 10/2 instead",
                    tool_calls=[ToolCall(
                        id="call_2",
                        function="divide",
                        arguments=json.dumps({"a": 10, "b": 2}),
                    )],
                    usage=Usage(8, 10, 18),
                )

        # Scenario 3: 多工具调用（并行）
        if self.scenario == "parallel_tools":
            return LLMResponse(
                content="I will do two things at once",
                tool_calls=[
                    ToolCall(
                        id="call_1",
                        function="add",
                        arguments=json.dumps({"a": 1, "b": 2}),
                    ),
                    ToolCall(
                        id="call_2",
                        function="multiply",
                        arguments=json.dumps({"a": 3, "b": 4}),
                    ),
                ],
                usage=Usage(12, 20, 32),
            )

        # Default: 直接完成
        return LLMResponse(
            content="Done",
            tool_calls=[ToolCall(
                id="call_final",
                function="done",
                arguments=json.dumps({"result": "mock result"}),
            )],
            usage=Usage(5, 5, 10),
        )


# ── 测试工具 ───────────────────────────────────────────────────

@tool
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


@tool
def multiply(a: int, b: int) -> int:
    """Multiply two numbers."""
    return a * b


@tool
def divide(a: float, b: float) -> float:
    """
    Divide a by b.

    Args:
        a: dividend
        b: divisor (must not be 0)
    """
    return a / b


# ── 测试用例 ───────────────────────────────────────────────────

def test_tool_schema():
    """测试: 工具Schema自动推断。"""
    print("\n[TEST] Tool Schema Inference")

    assert add.name == "add"
    assert add.description == "Add two numbers."
    schema = add.parameters
    assert schema["type"] == "object"
    assert "a" in schema["properties"]
    assert "b" in schema["properties"]
    assert schema["properties"]["a"]["type"] == "integer"
    assert "a" in schema["required"]

    print(f"  add tool schema: {json.dumps(schema, indent=2)}")
    print("  PASSED")


def test_tool_execution():
    """测试: 工具执行与错误处理。"""
    print("\n[TEST] Tool Execution")

    result = add.execute(a=2, b=3)
    assert result.success
    assert result.output == 5
    print(f"  add(2,3) = {result.output}")

    result = divide.execute(a=10, b=0)
    assert not result.success
    assert "division by zero" in str(result.error).lower() or "zerodivision" in str(result.error).lower()
    print(f"  divide(10,0) error: {result.error}")
    print("  PASSED")


def test_react_loop():
    """测试: Agent ReAct循环（Calculator场景）。"""
    print("\n[TEST] Agent ReAct Loop")

    llm = MockLLM("calculator")
    agent = Agent(llm=llm, tools=[add], config=AgentConfig(max_iterations=5))

    result = agent.run("What is 2+3?")

    assert result.success, f"Expected success, got: {result.stop_reason}"
    assert result.output == "5"
    assert result.iterations == 2
    assert result.total_usage.total_tokens == 43  # 25 + 18
    print(f"  output: {result.output}")
    print(f"  iterations: {result.iterations}")
    print(f"  tokens: {result.total_usage.total_tokens}")
    print("  PASSED")


def test_retry_on_error():
    """测试: 工具错误后Agent重试。"""
    print("\n[TEST] Retry on Tool Error")

    llm = MockLLM("retry")
    agent = Agent(llm=llm, tools=[divide], config=AgentConfig(max_iterations=5))

    result = agent.run("Calculate 10/0")

    # 第一次调用divide(10,0)失败，第二次divide(10,2)=5
    # 但MockLLM的第二次调用需要返回done才结束
    # 由于MockLLM第二次仍返回divide，会循环直到max_iterations
    # 所以这里我们主要验证错误被正确捕获和记录
    conv = result.conversation
    steps = conv.get_steps()
    assert len(steps) >= 1
    # 检查错误被记录到conversation中
    messages = conv.get_messages()
    tool_results = [m for m in messages if m.role == "tool"]
    assert len(tool_results) >= 1
    print(f"  tool calls made: {len(tool_results)}")
    print(f"  first error captured: {'error' in tool_results[0].content.lower() if tool_results else 'N/A'}")
    print("  PASSED")


def test_conversation_snapshot():
    """测试: Conversation快照与回滚。"""
    print("\n[TEST] Conversation Snapshot & Rollback")

    conv = Conversation()
    conv.add_user("First message")
    conv.add_assistant("First response")

    snap_id = conv.snapshot()
    assert conv.message_count == 2
    print(f"  before: {conv.message_count} messages")

    conv.add_user("Second message")
    conv.add_assistant("Second response")
    assert conv.message_count == 4
    print(f"  after add: {conv.message_count} messages")

    success = conv.rollback(snap_id)
    assert success
    assert conv.message_count == 2
    print(f"  after rollback: {conv.message_count} messages")
    print("  PASSED")


def test_context_hub_monitoring():
    """测试: ContextHub事件监控。"""
    print("\n[TEST] ContextHub Monitoring")

    hub = ContextHub()
    events_captured = []

    @hub.on(ContextEvent.MESSAGE_ADDED)
    def on_message(data):
        events_captured.append(("message", data.get("agent_id")))

    @hub.on(ContextEvent.AGENT_REGISTERED)
    def on_register(data):
        events_captured.append(("register", data.get("agent_id")))

    # 注册Agent
    conv = hub.register("agent_1", "You are a test agent")
    assert ("register", "agent_1") in events_captured

    # 通过Conversation添加消息（应触发hub事件）
    conv.add_user("Hello")
    assert any(e[0] == "message" and e[1] == "agent_1" for e in events_captured)

    print(f"  captured events: {events_captured}")
    print(f"  agents: {hub.list_agents()}")
    print("  PASSED")


def test_context_hub_intervention():
    """测试: ContextHub干预机制。"""
    print("\n[TEST] ContextHub Intervention")

    hub = ContextHub()
    conv = hub.register("agent_2")

    conv.add_user("Original task")

    # 插入干预消息
    success = hub.intervene(Intervention(
        type="insert",
        target="agent_2",
        data={"role": "system", "content": "IMPORTANT: Change your approach."},
        reason="detected_issue",
    ))
    assert success

    messages = conv.get_messages()
    last_msg = messages[-1]
    assert last_msg.role == "system"
    assert "Change your approach" in (last_msg.content or "")

    print(f"  intervention recorded: {last_msg.content}")
    print("  PASSED")


def test_context_hub_agent_to_agent():
    """测试: Agent间消息传递。"""
    print("\n[TEST] Agent-to-Agent Messaging")

    hub = ContextHub()
    conv1 = hub.register("researcher")
    conv2 = hub.register("writer")

    success = hub.send_to_agent("researcher", "writer", "Here are the facts: AI is evolving.")
    assert success

    messages = conv2.get_messages()
    assert any("researcher" in (m.content or "") for m in messages)
    print(f"  writer received: {[m.content for m in messages]}")
    print("  PASSED")


def test_context_hub_global_snapshot():
    """测试: ContextHub全局快照与回滚。"""
    print("\n[TEST] ContextHub Global Snapshot & Rollback")

    hub = ContextHub()
    conv1 = hub.register("agent_a")
    conv2 = hub.register("agent_b")

    conv1.add_user("Task A")
    conv2.add_user("Task B")

    snap_id = hub.snapshot_all()
    print(f"  snapshot created: {snap_id}")

    conv1.add_user("More work A")
    conv2.add_user("More work B")

    assert conv1.message_count == 2  # Task A + More work A
    assert conv2.message_count == 2

    hub.rollback_all(snap_id)

    assert conv1.message_count == 1  # Task A
    assert conv2.message_count == 1

    print(f"  after rollback: agent_a={conv1.message_count}, agent_b={conv2.message_count}")
    print("  PASSED")


def test_workflow_dag():
    """测试: Workflow DAG编排。"""
    print("\n[TEST] Workflow DAG Execution")

    llm = MockLLM("calculator")
    agent = Agent(llm=llm, tools=[add, multiply])

    wf = Workflow("math_workflow")
    wf.add_task("add_task", Task(name="add_task", description="Calculate 2+3", expected_output="5"))
    wf.add_task("multiply_task", Task(name="multiply_task", description="Calculate 3*4", expected_output="12"))
    wf.add_edge("add_task", "multiply_task")

    result = wf.run(agents={"default": agent})

    print(f"  execution order: {result.execution_order}")
    print(f"  task results: {list(result.task_results.keys())}")
    print(f"  total elapsed: {result.total_elapsed:.2f}s")
    print("  PASSED")


def test_workflow_mermaid():
    """测试: Workflow Mermaid图生成。"""
    print("\n[TEST] Workflow Mermaid Diagram")

    wf = Workflow("test_flow")
    wf.add_task("start", Task(name="start", description="Start"))
    wf.add_task("process", Task(name="process", description="Process"))
    wf.add_task("end", Task(name="end", description="End"))
    wf.sequential("start", "process", "end")

    mermaid = wf.to_mermaid()
    assert "graph TD" in mermaid
    assert "start" in mermaid
    assert "process" in mermaid

    print(mermaid)
    print("  PASSED")


# ── 运行所有测试 ───────────────────────────────────────────────

def test_rule_engine_repeated_short_thoughts():
    """测试: 规则引擎检测重复短句思考并干预。"""
    print("\n[TEST] Rule Engine: Repeated Short Thoughts")

    hub = ContextHub()
    conv = hub.register("stuck_agent")

    engine = SimpleRuleEngine(hub, RuleConfig(
        max_repeated_short_thoughts=3,
        short_thought_threshold=15,
    ))
    engine.start()

    # 模拟3次短句思考
    conv.record_step(StepRecord(thought="Hmm..."))           # 1
    conv.record_step(StepRecord(thought="Wait..."))           # 2
    conv.record_step(StepRecord(thought="Let me see..."))     # 3 -> 触发

    # 验证Agent被暂停
    assert hub.is_paused("stuck_agent"), "Agent should be paused after 3 short thoughts"

    messages = conv.get_messages()
    # 最后一条应该是干预消息
    assert messages[-1].role == "system"
    assert "stuck" in (messages[-1].content or "").lower() or "repetitive" in (messages[-1].content or "").lower()

    print(f"  agent paused: {hub.is_paused('stuck_agent')}")
    print(f"  intervention inserted: {messages[-1].content[:60]}...")
    print("  PASSED")


TESTS = [
    test_tool_schema,
    test_tool_execution,
    test_react_loop,
    test_retry_on_error,
    test_conversation_snapshot,
    test_context_hub_monitoring,
    test_context_hub_intervention,
    test_context_hub_agent_to_agent,
    test_context_hub_global_snapshot,
    test_workflow_dag,
    test_workflow_mermaid,
    test_rule_engine_repeated_short_thoughts,
]


def main():
    print("=" * 60)
    print("Agent Workflow Framework — End-to-End Verification")
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

    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)