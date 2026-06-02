"""
Workflow 预设构造器 — 常见模式的快捷方式。

设计原则:
- 固定链是 DAG 的子集（没有分叉的 DAG 就是链）
- 并行组是 DAG 的一层（同入度的节点为一层）
- 所有预设最终都转化为 WorkflowEngine 的 DAG 结构

支持的预设模式:
1. SequentialWorkflow — 纯顺序链
2. ParallelGroup — 并行组
3. MapReduce — 分治模式（Map 并行 → Reduce 汇总）
4. ConditionalBranch — 条件分支
"""
from __future__ import annotations

from typing import Any, Callable

from orchestration.task import Task
from orchestration.workflow.engine import Node, WorkflowEngine


# ── 纯顺序链 ────────────────────────────────────────────

def sequential_workflow(
    name: str,
    steps: list[tuple[str, Task, str]],
    **kwargs: Any,
) -> WorkflowEngine:
    """
    纯顺序链预设。

    Args:
        steps: [(task_name, Task, agent_id), ...]
        **kwargs: 传递给 WorkflowEngine 的额外参数

    Example:
        wf = sequential_workflow("pipeline", [
            ("design", Task("design", "Design..."), "architect"),
            ("code", Task("code", "Code..."), "coder"),
            ("test", Task("test", "Test..."), "tester"),
        ])
    """
    return WorkflowEngine.chain(name, steps, **kwargs)


# ── 含并行组的链 ────────────────────────────────────────

def parallel_workflow(
    name: str,
    steps: list,
    **kwargs: Any,
) -> WorkflowEngine:
    """
    含并行组的链预设。

    steps 格式:
        [(task_name, Task, agent_id), ...]                          — 顺序步骤
        [[(task_name, Task, agent_id), ...], ...]                   — 并行组（内层list）

    Example:
        wf = parallel_workflow("game", [
            ("design", Task("design", "Design game"), "architect"),
            [  # 并行开发两个模块
                ("track", Task("track", "Develop track"), "coder"),
                ("car", Task("car", "Develop car"), "coder"),
            ],
            ("integrate", Task("integrate", "Merge modules"), "coder"),
        ])
    """
    return WorkflowEngine.chain(name, steps, **kwargs)


# ── MapReduce 模式 ─────────────────────────────────────

def mapreduce_workflow(
    name: str,
    map_tasks: list[tuple[str, Task, str]],
    reduce_task: tuple[str, Task, str],
    **kwargs: Any,
) -> WorkflowEngine:
    """
    MapReduce 分治模式。

    所有 Map Task 并行执行，完成后结果汇总到 Reduce Task。

    Args:
        map_tasks: [(map_name, Task, agent_id), ...] — 并行执行的子任务
        reduce_task: (reduce_name, Task, agent_id) — 汇总任务

    Example:
        wf = mapreduce_workflow("analysis", [
            ("map_a", Task("Analyze A"), "agent1"),
            ("map_b", Task("Analyze B"), "agent2"),
            ("map_c", Task("Analyze C"), "agent3"),
        ], ("reduce", Task("Summarize all"), "agent1"))
    """
    wf = WorkflowEngine(name=name, **kwargs)

    # 注册所有 Map Task（无依赖，入度为0 → 第一层）
    map_names: list[str] = []
    for tname, ttask, tagent in map_tasks:
        wf.add_task(tname, Node(task=ttask, agent_id=tagent, parallel=True))
        map_names.append(tname)

    # 注册 Reduce Task
    rname, rtask, ragent = reduce_task
    wf.add_task(rname, Node(task=rtask, agent_id=ragent))

    # 所有 Map → Reduce
    for mname in map_names:
        wf.add_edge(mname, rname)

    return wf


# ── 条件分支模式 ───────────────────────────────────────

def conditional_workflow(
    name: str,
    start_task: tuple[str, Task, str],
    branches: list[tuple[str, Task, str, Callable[[dict[str, Any]], bool]]],
    end_task: tuple[str, Task, str] | None = None,
    **kwargs: Any,
) -> WorkflowEngine:
    """
    条件分支模式。

    Start → [Branch A (condition)] → End
         → [Branch B (condition)] →
         → [Branch C (condition)] →

    Args:
        start_task: (name, Task, agent_id) — 起始任务
        branches: [(name, Task, agent_id, condition_fn), ...] — 条件分支
        end_task: 可选的汇聚任务

    Example:
        wf = conditional_workflow("route", (
            "analyze", Task("Analyze input"), "agent1"
        ), [
            ("code", Task("Write code"), "agent2",
             lambda o: "programming" in str(o)),
            ("write", Task("Write article"), "agent2",
             lambda o: "writing" in str(o)),
            ("research", Task("Do research"), "agent2",
             lambda o: "research" in str(o)),
        ])
    """
    wf = WorkflowEngine(name=name, **kwargs)

    sname, stask, sagent = start_task
    wf.add_task(sname, Node(task=stask, agent_id=sagent))

    for tname, ttask, tagent, tcond in branches:
        wf.add_task(tname, Node(task=ttask, agent_id=tagent))
        wf.add_conditional_edge(sname, tname, tcond)

    if end_task:
        ename, etask, eagent = end_task
        wf.add_task(ename, Node(task=etask, agent_id=eagent))
        for tname, _, _, _ in branches:
            wf.add_edge(tname, ename)

    return wf


# ── 构建与运行辅助 ────────────────────────────────────

def run_chain(
    steps: list,
    agents: dict[str, Any],
    hub: Any | None = None,
    name: str = "chain",
    **kwargs: Any,
) -> Any:
    """
    一键构建并运行固定链。

    Example:
        result = run_chain([
            ("design", Task("Design..."), "architect"),
            ("code", Task("Code..."), "coder"),
        ], agents={"architect": agent1, "coder": agent2})
    """
    wf = WorkflowEngine.chain(name, steps, **kwargs)
    return wf.run(agents=agents, hub=hub)
