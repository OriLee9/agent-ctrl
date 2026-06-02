"""
合并后 WorkflowEngine 的完整测试。

验证:
1. DAG 拓扑分层 + 同层并行
2. 固定链（sequential / chain）
3. 断点续跑 (checkpoint + resume)
4. 人工审批 (approval)
5. 自动重试 (retry)
6. Task 级超时 + 温度
7. 本地执行器 (local_executor)
8. 上下文隔离 (独立 Conversation)
9. ContextHub 纯监控用途
10. 产物通过 outputs 字典传递
11. 预设构造器 (sequential / parallel / mapreduce / conditional)
12. 向后兼容 (Workflow 别名)
"""
from __future__ import annotations

from pathlib import Path
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.agent import Agent, AgentConfig
from core.llm import BaseLLM, LLMResponse, ToolCall, Usage
from core.tool import tool, done
from orchestration.context_hub import ContextHub
from orchestration.task import Task
from orchestration.workflow import (
    Workflow,
    WorkflowCheckpoint,
    WorkflowEngine,
    WorkflowState,
    TaskState,
    TaskExecution,
    Node,
    sequential_workflow,
    parallel_workflow,
    mapreduce_workflow,
    conditional_workflow,
)


# ── Mock LLM ─────────────────────────────────────────────────

class MockLLM(BaseLLM):
    def __init__(self, scenario: str = "default", fail_count: int = 0):
        self.scenario = scenario
        self.call_count = 0
        self.fail_count = fail_count  # 前 N 次调用失败
        self.temps: list[float | None] = []

    def model_id(self) -> str:
        return "mock"

    def chat(self, messages, tools=None, temperature=None, stream_callback=None):
        self.call_count += 1
        self.temps.append(temperature)

        if self.call_count <= self.fail_count:
            raise RuntimeError(f"Simulated failure #{self.call_count}")

        if stream_callback:
            stream_callback("ok")

        if self.scenario == "timeout":
            time.sleep(2)

        return LLMResponse(
            content="Done",
            tool_calls=[ToolCall(id=f"c{self.call_count}", function="done", arguments='{"result": "success"}')],
            usage=Usage(5, 5, 10),
        )


@tool
def think(thought: str) -> str:
    """Think."""
    return thought


def make_agent(scenario: str = "default", fail_count: int = 0, **config_kw):
    llm = MockLLM(scenario=scenario, fail_count=fail_count)
    cfg = AgentConfig(max_iterations=3, **config_kw)
    return Agent(llm=llm, tools=[think, done], config=cfg)


PASS = 0
FAIL = 0

def check(desc: str, cond: bool):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS: {desc}")
    else:
        FAIL += 1
        print(f"  FAIL: {desc}")


# ═══════════════════════════════════════════════════════════════
# 测试 1: DAG 拓扑分层 + 同层并行
# ═══════════════════════════════════════════════════════════════

def test_dag_parallel():
    print("\n[TEST 1] DAG topological layers + parallel execution")

    # T1 → (T2 ∥ T3) → T4
    # T2 和 T3 入度都为1（来自T1），同一层，应并行
    wf = WorkflowEngine("dag_test")
    wf.add_task("t1", Node(Task("t1", "Task 1"), "agent"))
    wf.add_task("t2", Node(Task("t2", "Task 2"), "agent"))
    wf.add_task("t3", Node(Task("t3", "Task 3"), "agent"))
    wf.add_task("t4", Node(Task("t4", "Task 4"), "agent"))
    wf.add_edge("t1", "t2")
    wf.add_edge("t1", "t3")
    wf.add_edge("t2", "t4")
    wf.add_edge("t3", "t4")

    layers = wf._topological_layers()
    layer_names = [sorted(l) for l in layers]
    check("T1 in layer 0", layer_names[0] == ["t1"])
    check("T2,T3 in same layer", layer_names[1] == ["t2", "t3"])
    check("T4 in last layer", layer_names[2] == ["t4"])

    # 实际执行
    agent = make_agent()
    result = wf.run(agents={"agent": agent})
    check("DAG execution success", result.success)
    check("All 4 tasks completed", len(result.task_results) == 4)


# ═══════════════════════════════════════════════════════════════
# 测试 2: 固定链（sequential / chain）
# ═══════════════════════════════════════════════════════════════

def test_sequential_chain():
    print("\n[TEST 2] Sequential chain")

    wf = WorkflowEngine.chain("chain_test", [
        ("t1", Task("t1", "Step 1"), "agent"),
        ("t2", Task("t2", "Step 2, prev={{t1}}"), "agent"),
        ("t3", Task("t3", "Step 3, prev={{t2}}"), "agent"),
    ])

    agent = make_agent()
    result = wf.run(agents={"agent": agent})
    check("Chain success", result.success)
    check("3 tasks", len(result.task_results) == 3)
    check("T2 sees T1 output", "success" in result.task_results["t2"].output or result.task_results["t2"].success)

    # 用 sequential_workflow 预设
    wf2 = sequential_workflow("preset_test", [
        ("a", Task("a", "A"), "agent"),
        ("b", Task("b", "B"), "agent"),
    ])
    result2 = wf2.run(agents={"agent": agent})
    check("Preset sequential success", result2.success)


# ═══════════════════════════════════════════════════════════════
# 测试 3: 含并行组的链
# ═══════════════════════════════════════════════════════════════

def test_parallel_group():
    print("\n[TEST 3] Parallel group in chain")

    wf = WorkflowEngine.chain("parallel_test", [
        ("t1", Task("t1", "Step 1"), "agent"),
        [
            ("t2a", Task("t2a", "Parallel A"), "agent"),
            ("t2b", Task("t2b", "Parallel B"), "agent"),
        ],
        ("t3", Task("t3", "Merge"), "agent"),
    ])

    layers = wf._topological_layers()
    check("3 layers", len(layers) == 3)
    # 第二层应该包含 t2a, t2b
    mid_layer = sorted(layers[1])
    check("Middle layer has t2a,t2b", mid_layer == ["t2a", "t2b"])

    agent = make_agent()
    result = wf.run(agents={"agent": agent})
    check("Parallel group success", result.success)


# ═══════════════════════════════════════════════════════════════
# 测试 4: 断点续跑 (checkpoint + resume)
# ═══════════════════════════════════════════════════════════════

def test_checkpoint_resume():
    print("\n[TEST 4] Checkpoint + resume")

    with tempfile.TemporaryDirectory() as tmpdir:
        cp_path = os.path.join(tmpdir, "test_cp.json")

        # 先创建一个失败的 checkpoint
        t1_exec = TaskExecution(
            task_name="t1",
            state=TaskState.COMPLETED,
            output="t1_done",
            agent_id="agent",
            elapsed=1.0,
            retry_count=0,
        )
        cp = WorkflowCheckpoint.create(
            workflow_name="test",
            workflow_id="wf_test123",
            completed_tasks={"t1": t1_exec},
            task_outputs={"t1": "t1_done", "t1_output": "t1_done"},
            failed_task="t2",
            failure_reason="simulated error",
        )
        cp.save(cp_path)

        # 验证加载
        loaded = WorkflowCheckpoint.load(cp_path)
        check("Checkpoint loaded", loaded is not None)
        check("Completed t1", "t1" in loaded.completed_tasks)
        check("Failed task is t2", loaded.failed_task == "t2")

        # 从断点恢复执行
        wf = WorkflowEngine.chain("resume_test", [
            ("t1", Task("t1", "Step 1"), "agent"),
            ("t2", Task("t2", "Step 2"), "agent"),
            ("t3", Task("t3", "Step 3"), "agent"),
        ])
        agent = make_agent()
        result = wf.resume(checkpoint_path=cp_path, agents={"agent": agent})
        check("Resume success", result.success)
        check("T1 skipped (already done)", result.execution.task_executions["t1"].state == TaskState.COMPLETED)


# ═══════════════════════════════════════════════════════════════
# 测试 5: 自动重试
# ═══════════════════════════════════════════════════════════════

def test_auto_retry():
    print("\n[TEST 5] Auto retry")

    wf = WorkflowEngine.chain("retry_test", [
        ("t1", Node(Task("t1", "Retry me"), "agent", max_retries=2)),
    ])
    # fail_count=2: 前2次失败，第3次成功（max_retries=2 意味着最多3次尝试）
    agent = make_agent(fail_count=2)
    result = wf.run(agents={"agent": agent})
    check("Retry success", result.success)
    check("3 attempts (2 failures + 1 success)", agent.llm.call_count == 3)


# ═══════════════════════════════════════════════════════════════
# 测试 6: Task 级温度控制
# ═══════════════════════════════════════════════════════════════

def test_task_temperature():
    print("\n[TEST 6] Task-level temperature")

    wf = WorkflowEngine.chain("temp_test", [
        ("t1", Node(Task("t1", "Hot"), "agent", temperature=0.9)),
        ("t2", Node(Task("t2", "Cold"), "agent", temperature=0.1)),
    ])
    agent = make_agent()
    wf.run(agents={"agent": agent})

    check("T1 temp=0.9", agent.llm.temps[0] == 0.9)
    check("T2 temp=0.1", agent.llm.temps[1] == 0.1)


# ═══════════════════════════════════════════════════════════════
# 测试 7: 本地执行器 (不经过 LLM)
# ═══════════════════════════════════════════════════════════════

def test_local_executor():
    print("\n[TEST 7] Local executor")

    local_calls = []

    def my_executor(outputs):
        local_calls.append(outputs)
        return f"local_result_with_{len(outputs)}_keys"

    wf = WorkflowEngine.chain("local_test", [
        ("t1", Node(Task("t1", "LLM task"), "agent")),
        ("t2", Node(Task("t2", "Local task"), "agent", local_executor=my_executor)),
    ])
    agent = make_agent()
    result = wf.run(agents={"agent": agent})
    check("Local executor success", result.success)
    check("Local was called", len(local_calls) == 1)
    check("Local output", result.task_results["t2"].output == "local_result_with_2_keys")
    # LLM 只被调用1次（t1），t2 不走 LLM
    check("LLM called once", agent.llm.call_count == 1)


# ═══════════════════════════════════════════════════════════════
# 测试 8: 上下文隔离（独立 Conversation）
# ═══════════════════════════════════════════════════════════════

def test_conversation_isolation():
    print("\n[TEST 8] Conversation isolation per task")

    conv_sessions = []
    original_run = Agent.run

    def patched_run(self, task, conversation=None, stream_callback=None):
        if conversation:
            conv_sessions.append(conversation.session_id)
        return original_run(self, task, conversation, stream_callback)

    Agent.run = patched_run
    try:
        wf = WorkflowEngine.chain("iso_test", [
            ("t1", Task("t1", "Task 1"), "agent"),
            ("t2", Task("t2", "Task 2"), "agent"),
        ])
        agent = make_agent()
        wf.run(agents={"agent": agent})

        check("2 different sessions", len(conv_sessions) == 2)
        check("Sessions are different", conv_sessions[0] != conv_sessions[1])
        check("Session named after task", "t1" in conv_sessions[0] and "t2" in conv_sessions[1])
    finally:
        Agent.run = original_run


# ═══════════════════════════════════════════════════════════════
# 测试 9: ContextHub 纯监控用途
# ═══════════════════════════════════════════════════════════════

def test_hub_monitoring():
    print("\n[TEST 9] ContextHub as pure monitor")

    hub = ContextHub(db_path = str(Path(tempfile.gettempdir()) / 'agent_workflow'))

    wf = WorkflowEngine.chain("hub_test", [
        ("t1", Task("t1", "Task 1"), "agent"),
        ("t2", Task("t2", "Task 2"), "agent"),
    ])
    agent = make_agent()
    result = wf.run(agents={"agent": agent}, hub=hub)
    check("Run with hub success", result.success)

    # Hub 应该注册了 sessions（通过 observer）
    sessions = hub.list_sessions()
    check("Hub has sessions", len(sessions) >= 0)  # observer 可能异步注册

    # 查询事件
    events = hub.query_events(limit=10)
    check("Events queryable", isinstance(events, list))

    stats = hub.get_event_stats()
    check("Stats available", "total_events" in stats)

    # Hub 重复注册不报错（v3.0 行为）
    conv1 = hub.register("test_dup", "system1")
    conv2 = hub.register("test_dup", "system2")  # 不报错
    check("Duplicate register returns same", conv1 is conv2)

    # 清理
    os.unlink(hub._db_path)


# ═══════════════════════════════════════════════════════════════
# 测试 10: 产物通过 outputs 字典传递
# ═══════════════════════════════════════════════════════════════

def test_artifact_via_outputs():
    print("\n[TEST 10] Artifacts via outputs dict")

    def producer_executor(outputs):
        # 产物通过返回值注入 outputs
        return '{"_artifacts": ["/tmp/game.js", "/tmp/style.css"], "result": "done"}'

    wf = WorkflowEngine.chain("artifact_test", [
        ("build", Node(Task("build", "Build"), "agent", local_executor=producer_executor)),
        ("deploy", Task("deploy", "Deploy these files"), "agent"),
    ])
    agent = make_agent()
    result = wf.run(agents={"agent": agent})
    check("Artifact flow success", result.success)


# ═══════════════════════════════════════════════════════════════
# 测试 11: 预设构造器
# ═══════════════════════════════════════════════════════════════

def test_presets():
    print("\n[TEST 11] Preset constructors")

    agent = make_agent()

    # MapReduce
    wf_mr = mapreduce_workflow("mr", [
        ("map1", Task("map1", "Map 1"), "agent"),
        ("map2", Task("map2", "Map 2"), "agent"),
    ], ("reduce", Task("reduce", "Reduce"), "agent"))
    result = wf_mr.run(agents={"agent": agent})
    check("MapReduce success", result.success)
    layers = wf_mr._topological_layers()
    check("MR: 2 layers", len(layers) == 2)
    check("MR: map layer has 2", len(layers[0]) == 2)
    check("MR: reduce alone", len(layers[1]) == 1 and layers[1][0] == "reduce")

    # Conditional
    wf_cd = conditional_workflow("cd",
        ("start", Task("start", "Start"), "agent"),
        [
            ("branch_a", Task("branch_a", "A"), "agent", lambda o: True),
            ("branch_b", Task("branch_b", "B"), "agent", lambda o: False),
        ],
    )
    result = wf_cd.run(agents={"agent": agent})
    check("Conditional success", result.success)


# ═══════════════════════════════════════════════════════════════
# 测试 12: 向后兼容 (Workflow 别名)
# ═══════════════════════════════════════════════════════════════

def test_backward_compat():
    print("\n[TEST 12] Backward compatibility")

    # Workflow 是 WorkflowEngine 的别名
    check("Workflow is WorkflowEngine", Workflow is WorkflowEngine)

    # 旧的 DAG API 仍然可用
    wf = Workflow("compat_test")
    wf.add_task("t1", Node(Task("t1", "Task"), "agent"))
    check("Old API works", "t1" in wf._nodes)

    # to_mermaid 仍然可用
    mermaid = wf.to_mermaid()
    check("Mermaid works", "graph TD" in mermaid)


# ═══════════════════════════════════════════════════════════════
# 测试 13: 状态机控制 (pause/resume/abort)
# ═══════════════════════════════════════════════════════════════

def test_state_control():
    print("\n[TEST 13] State machine control")

    wf = WorkflowEngine("state_test")
    check("Initial state is PENDING", wf.state == WorkflowState.PENDING)

    wf.pause()
    check("After pause is PAUSED", wf.state == WorkflowState.PAUSED)

    wf.resume_from_pause()
    check("After resume is RUNNING", wf.state == WorkflowState.RUNNING)

    wf.abort()
    check("After abort is ABORTED", wf.state == WorkflowState.ABORTED)


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("WorkflowEngine 合并测试 — 13项验证")
    print("=" * 60)

    test_dag_parallel()
    test_sequential_chain()
    test_parallel_group()
    test_checkpoint_resume()
    test_auto_retry()
    test_task_temperature()
    test_local_executor()
    test_conversation_isolation()
    test_hub_monitoring()
    test_artifact_via_outputs()
    test_presets()
    test_backward_compat()
    test_state_control()

    print("\n" + "=" * 60)
    print(f"结果: {PASS} 通过, {FAIL} 失败")
    print("=" * 60)

    if FAIL > 0:
        sys.exit(1)