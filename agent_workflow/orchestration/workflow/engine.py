"""
Workflow 执行引擎 — DAG 表达能力 + V2 生产特性。

核心设计:
- 数据结构: DAG (dict[str, Node] + 邻接表 + 入度)
- 执行引擎: Kahn 拓扑分层 → 同层 asyncio.gather 并行
- 断点续跑: WorkflowCheckpoint JSON 序列化
- 人工审批: asyncio.Event 非阻塞等待
- 自动重试: max_retries + retry_delay
- Task 级配置: timeout / temperature / local_executor
- 上下文隔离: 每个 Task 新建独立 Conversation
- ContextHub: 退化为纯监控用途（不再持有 Conversation）
- 产物传递: 通过 outputs 字典显式传递，不硬编码路径

合并来源:
- workflow.py 的 DAG 拓扑并行能力
- workflow_v2.py 的断点/审批/重试/超时/温度/本地执行
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable


def _run_asyncio(coro):
    """在任意环境中运行 asyncio coroutine，处理嵌套事件循环。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # 没有运行中的事件循环，直接用 asyncio.run
        return asyncio.run(coro)
    # 已有事件循环在运行（如 Jupyter），在新线程中创建新 loop 执行
    def _run_in_new_loop():
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        try:
            return new_loop.run_until_complete(coro)
        finally:
            new_loop.close()
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_run_in_new_loop).result()

from core.agent import Agent, AgentResult
from core.memory import Conversation
from core.review_tools import (
    ReviewDecision,
    clear_review_decision,
    get_review_decision,
    review_decision_tool,
    reviewer_system_prompt,
    set_review_decision,
)
from orchestration.context_hub import ContextHub
from orchestration.task import Task
from orchestration.workflow.checkpoint import WorkflowCheckpoint
from orchestration.workflow.state import (
    TaskExecution,
    TaskState,
    WorkflowExecution,
    WorkflowState,
)
from validation.validators import HtmlValidator, JavaScriptValidator


# ── 产物收集器（替代硬编码路径扫描）─────────────────────────

@dataclass
class ArtifactCollector:
    """通过 outputs 字典显式收集产物信息。"""

    output_dir: str | None = None

    def collect(self, outputs: dict[str, Any]) -> str:
        """从 outputs 字典中提取产物列表。"""
        # 1. 优先从 outputs 中读取 _artifacts 键
        artifacts: list[str] = outputs.get("_artifacts", [])
        if artifacts:
            return "\n".join(f"  - {a}" for a in artifacts)

        # 2. 退化为目录扫描（兼容旧行为，但路径由外部传入）
        if self.output_dir and os.path.exists(self.output_dir):
            files = []
            for f in sorted(os.listdir(self.output_dir)):
                if f.endswith(".log") or f.endswith(".py"):
                    continue
                fpath = os.path.join(self.output_dir, f)
                if os.path.isfile(fpath):
                    size = os.path.getsize(fpath)
                    files.append(f"  - {f}: {size:,} bytes")
            return "\n".join(files) if files else ""

        return ""


# ── DAG 节点 ────────────────────────────────────────────────

@dataclass
class Node:
    """DAG 节点 — 包含 Task + V2 级执行配置。"""

    task: Task
    agent_id: str
    # 条件执行
    condition: Callable[[dict[str, Any]], bool] | None = None
    # 人工审批
    requires_approval: bool = False
    # Task 级配置
    timeout: int | None = None
    max_retries: int = 2
    retry_delay: int = 3
    temperature: float | None = None
    # 工具白名单（None=不限制，使用agent全部工具）
    allowed_tools: list[str] | None = None
    # 并行标记（与同层自动并行共存）
    parallel: bool = True  # DAG 同层默认并行
    # 本地执行器（不经过 LLM）
    local_executor: Callable[[dict[str, Any]], str] | None = None
    # 产物收集
    collect_artifacts: bool = True
    # 审查门控：若 review 输出含 CRITICAL，自动重跑（0=不重跑）
    max_passes: int = 1
    review_gate: str | None = None  # 哪个 task 的输出作为审查标准
    # 循环条件：DAG 完成后若条件不满足则重复执行该 task
    loop_condition: Callable[[dict[str, Any]], bool] | None = None  # 返回 True=停止循环
    loop_max_iterations: int = 1  # 默认 1 = 不循环


@dataclass
class Edge:
    """DAG 边 — 带可选条件。"""

    condition: Callable[[dict[str, Any]], bool] | None = None


# ── 执行结果 ────────────────────────────────────────────────

@dataclass
class TaskResult:
    """单个 Task 的执行结果（兼容层）。"""

    task_name: str
    success: bool = False
    output: str = ""
    agent_id: str | None = None
    elapsed: float = 0.0
    error: str | None = None
    raw: AgentResult | None = None
    state: TaskState = TaskState.PENDING
    artifacts: list[str] = field(default_factory=list)


@dataclass
class WorkflowResult:
    """Workflow 的完整执行结果（兼容层）。"""

    workflow_id: str
    success: bool = False
    task_results: dict[str, TaskResult] = field(default_factory=dict)
    execution_order: list[str] = field(default_factory=list)
    total_elapsed: float = 0.0
    error: str | None = None
    execution: WorkflowExecution | None = None


# ── Workflow 引擎 ───────────────────────────────────────────

class WorkflowEngine:
    """
    合并后的 Workflow 引擎。

    DAG 能力（来自 workflow.py）:
        wf = WorkflowEngine("game")
        wf.add_task("design", Node(Task(...), "architect"))
        wf.add_task("code", Node(Task(...), "coder"))
        wf.add_edge("design", "code")
        result = wf.run(agents={"architect": a1, "coder": a2})

    固定链快捷方式（来自 workflow_v2.py）:
        wf = WorkflowEngine.chain("game", [
            ("design", Task(...), "architect"),
            ("code", Task(...), "coder"),
        ])
        result = wf.run(agents={"architect": a1, "coder": a2})

    并行组快捷方式:
        wf = WorkflowEngine.chain("game", [
            ("design", Task(...), "architect"),
            # T2 和 T3 并行执行
            [("track", Task(...), "coder"), ("car", Task(...), "coder")],
            ("integrate", Task(...), "coder"),
        ])
    """

    def __init__(
        self,
        name: str = "workflow",
        mode: str = "free",
        checkpoint_dir: str | None = None,
        auto_recover: bool = False,
    ):
        self.name = name
        self.mode = mode  # "free" | "fixed"
        self.workflow_id = f"wf_{uuid.uuid4().hex[:8]}"

        # DAG 结构
        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, list[str]] = {}      # 邻接表: from -> [to]
        self._indegree: dict[str, int] = {}           # 入度计数
        self._edge_conditions: dict[tuple[str, str], Callable] = {}  # 条件边

        # Agent / Hub
        self._agents: dict[str, Agent] = {}
        self._hub: ContextHub | None = None

        # Checkpoint
        self._checkpoint_dir = checkpoint_dir or os.environ.get("CHECKPOINT_DIR", "/tmp/agent_workflow/checkpoints")
        os.makedirs(self._checkpoint_dir, exist_ok=True)
        self._checkpoint_path = os.path.join(
            self._checkpoint_dir, f"{self.workflow_id}.json"
        )
        self._auto_recover = auto_recover

        # 执行状态
        self._state = WorkflowState.PENDING
        self._current_execution: WorkflowExecution | None = None
        self._approval_events: dict[str, asyncio.Event] = {}
        self._recovery_event = asyncio.Event()
        self._lock = threading.Lock()

        # 产物收集器
        self._artifact_collector = ArtifactCollector()

        # SubAgentManager 缓存（避免每次 task 执行重复实例化）
        self._sub_agent_managers: dict[str, SubAgentManager] = {}

        # 生命周期钩子
        self.on_task_start: Callable[[str, Node], None] | None = None
        self.on_task_end: Callable[[str, TaskExecution], None] | None = None
        self.on_task_complete: Callable[[str, TaskExecution], None] | None = None
        self.on_approval_needed: Callable[[str, Node], None] | None = None
        self.on_recovery_needed: Callable[[str, str, WorkflowCheckpoint], None] | None = None
        self.on_state_change: Callable[[WorkflowState], None] | None = None
        self.on_checkpoint: Callable[[str], None] | None = None
        self.on_complete: Callable[[WorkflowExecution], None] | None = None

    def _transition_state(
        self,
        new_state: WorkflowState,
        execution: WorkflowExecution | None = None,
    ) -> None:
        """统一状态转换，仅在调用方已持有 self._lock 时使用。"""
        if self._state == new_state:
            return
        self._state = new_state
        if execution:
            execution.state = new_state
        if self.on_state_change:
            self.on_state_change(new_state)

    # ── DAG 构建 ──────────────────────────────────────────

    def add_task(self, name: str, node: Node) -> "WorkflowEngine":
        """添加 DAG 节点。"""
        self._nodes[name] = node
        if name not in self._edges:
            self._edges[name] = []
        if name not in self._indegree:
            self._indegree[name] = 0
        return self

    def add_edge(self, from_task: str, to_task: str) -> "WorkflowEngine":
        """添加有向边: from_task → to_task。"""
        if from_task not in self._nodes or to_task not in self._nodes:
            raise ValueError(f"Unknown task: {from_task} or {to_task}")
        self._edges[from_task].append(to_task)
        self._indegree[to_task] = self._indegree.get(to_task, 0) + 1
        return self

    def add_conditional_edge(
        self,
        from_task: str,
        to_task: str,
        condition: Callable[[dict[str, Any]], bool],
    ) -> "WorkflowEngine":
        """添加条件边：只有 condition 返回 True 时才执行 to_task。"""
        self.add_edge(from_task, to_task)
        self._edge_conditions[(from_task, to_task)] = condition
        return self

    def sequential(self, *pairs: tuple[str, Node]) -> "WorkflowEngine":
        """快速定义顺序链: (name1, node1) → (name2, node2) → ..."""
        names: list[str] = []
        for name, node in pairs:
            self.add_task(name, node)
            names.append(name)
        for i in range(len(names) - 1):
            self.add_edge(names[i], names[i + 1])
        return self

    def register_agent(self, agent_id: str, agent: Agent) -> "WorkflowEngine":
        self._agents[agent_id] = agent
        return self

    def set_hub(self, hub: ContextHub) -> "WorkflowEngine":
        self._hub = hub
        return self

    # ── 预设构造器 ────────────────────────────────────────

    @classmethod
    def chain(
        cls,
        name: str,
        steps: list,
        **kwargs: Any,
    ) -> "WorkflowEngine":
        """
        从固定链构造 Workflow。

        steps 格式:
            [(name, Task, agent_id), ...]                              # 纯顺序
            [(name, Task, agent_id), [(name, Task, agent_id), ...]]    # 含并行组

        并行组: 内层 list 中的 Task 同层并行执行。
        正确 DAG: predecessor → {group members} → successor
        """
        wf = cls(name=name, **kwargs)

        # 解析 steps 为结构化的 segments
        # segment = {"type": "seq", "items": [(name, Node), ...]} |
        #           {"type": "par", "items": [(name, Node), ...]}
        segments: list[dict] = []

        def _extract(item: Any) -> tuple[str, Node]:
            if isinstance(item, tuple) and len(item) == 3:
                name, task, agent_id = item
                return (name, Node(task=task, agent_id=agent_id) if isinstance(task, Task) else task)
            elif isinstance(item, tuple) and len(item) == 2:
                return item
            raise ValueError(f"Invalid step: {item}")

        for item in steps:
            if isinstance(item, list):
                # 并行组
                members = [_extract(sub) for sub in item]
                for _, node in members:
                    node.parallel = True
                segments.append({"type": "par", "items": members})
            else:
                segments.append({"type": "seq", "items": [_extract(item)]})

        # 注册所有 Task
        for seg in segments:
            for name, node in seg["items"]:
                wf.add_task(name, node)

        # 连边: 相邻 segment 之间全连接
        # seq: [a] → next_seg  (a 连到 next_seg 所有)
        # par: [a,b] → next_seg (a,b 都连到 next_seg 所有)
        for i in range(len(segments) - 1):
            curr_names = [n for n, _ in segments[i]["items"]]
            next_names = [n for n, _ in segments[i + 1]["items"]]
            for cn in curr_names:
                for nn in next_names:
                    wf.add_edge(cn, nn)

        return wf

    # ── 同步执行入口 ──────────────────────────────────────

    def run(
        self,
        agents: dict[str, Agent] | None = None,
        hub: ContextHub | None = None,
        initial_inputs: dict[str, Any] | None = None,
        max_workers: int | None = None,
    ) -> WorkflowResult:
        """同步执行 — 内部调用异步实现。"""
        if agents:
            for aid, agent in agents.items():
                self.register_agent(aid, agent)
        if hub:
            self.set_hub(hub)

        # 清理旧 checkpoint
        if os.path.exists(self._checkpoint_path):
            os.remove(self._checkpoint_path)

        execution = WorkflowExecution(
            workflow_id=self.workflow_id,
            checkpoint_path=self._checkpoint_path,
        )
        self._current_execution = execution

        return _run_asyncio(
            self._run_async(execution, initial_inputs, max_workers)
        )

    def resume(
        self,
        checkpoint_path: str | None = None,
        agents: dict[str, Agent] | None = None,
        hub: ContextHub | None = None,
        max_workers: int | None = None,
    ) -> WorkflowResult:
        """从断点恢复执行。"""
        if agents:
            for aid, agent in agents.items():
                self.register_agent(aid, agent)
        if hub:
            self.set_hub(hub)

        path = checkpoint_path or self._checkpoint_path
        checkpoint = WorkflowCheckpoint.load(path)
        if not checkpoint:
            raise ValueError(f"No checkpoint found at {path}")

        execution = WorkflowExecution(
            workflow_id=checkpoint.workflow_id,
            checkpoint_path=path,
            task_executions=dict(checkpoint.completed_tasks),
        )
        self._current_execution = execution
        checkpoint.retry_count += 1
        self._recovery_event = asyncio.Event()

        return _run_asyncio(
            self._run_async(execution, checkpoint.task_outputs, max_workers, checkpoint)
        )

    # ── 异步核心执行 ──────────────────────────────────────

    async def _run_async(
        self,
        execution: WorkflowExecution,
        initial_inputs: dict[str, Any] | None = None,
        max_workers: int | None = None,
        checkpoint: WorkflowCheckpoint | None = None,
    ) -> WorkflowResult:
        """异步执行核心 — 拓扑分层 + 同层并行。"""
        start_time = time.time()
        result = WorkflowResult(workflow_id=self.workflow_id, execution=execution)

        with self._lock:
            self._transition_state(WorkflowState.RUNNING, execution)
            execution.started_at = time.time()

        # 初始化 outputs
        task_outputs: dict[str, Any] = dict(initial_inputs or {})
        if checkpoint:
            task_outputs.update(checkpoint.task_outputs)

        # 拓扑分层
        try:
            layers = self._topological_layers()
        except ValueError as e:
            result.error = str(e)
            execution.state = WorkflowState.FAILED
            execution.error = str(e)
            return result

        result.execution_order = [t for layer in layers for t in layer]

        # 确定起始层（断点续跑时跳过已完成层）
        start_layer = 0
        failed_task_name = checkpoint.failed_task if checkpoint else None

        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            for li, layer in enumerate(layers):
                    if self._state == WorkflowState.ABORTED:
                        execution.state = WorkflowState.ABORTED
                        break

                    # 暂停检查
                    while self._state == WorkflowState.PAUSED:
                        await asyncio.sleep(0.5)
                        if self._state == WorkflowState.ABORTED:
                            execution.state = WorkflowState.ABORTED
                            break
                    if execution.state == WorkflowState.ABORTED:
                        break

                    # 构建当前层可执行 Task
                    layer_tasks: list[tuple[str, Node]] = []
                    for task_name in layer:
                        # 断点续跑：跳过已完成的 Task
                        if checkpoint and task_name in checkpoint.completed_tasks:
                            cp_ex = checkpoint.completed_tasks[task_name]
                            execution.task_executions[task_name] = cp_ex
                            if cp_ex.state == TaskState.COMPLETED:
                                task_outputs[task_name] = cp_ex.output
                                if cp_ex.artifacts:
                                    task_outputs.setdefault("_artifacts", []).extend(
                                        cp_ex.artifacts
                                    )
                            continue

                        node = self._nodes[task_name]

                        # 条件检查（节点级 + 边级）
                        if node.condition and not node.condition(task_outputs):
                            ex = TaskExecution(task_name=task_name, state=TaskState.SKIPPED)
                            execution.task_executions[task_name] = ex
                            continue

                        # 条件边检查
                        skip = False
                        for (from_t, to_t), cond in self._edge_conditions.items():
                            if to_t == task_name and not cond(task_outputs):
                                skip = True
                                break
                        if skip:
                            ex = TaskExecution(task_name=task_name, state=TaskState.SKIPPED)
                            execution.task_executions[task_name] = ex
                            continue

                        layer_tasks.append((task_name, node))

                    if not layer_tasks:
                        continue

                    # 并行执行当前层
                    futures = [
                        self._execute_task_async(task_name, node, task_outputs, executor)
                        for task_name, node in layer_tasks
                    ]
                    layer_results = await asyncio.gather(*futures, return_exceptions=True)

                    # 收集结果
                    any_failed = False
                    for (task_name, _), task_res in zip(layer_tasks, layer_results):
                        if isinstance(task_res, Exception):
                            exec_rec = TaskExecution(
                                task_name=task_name,
                                state=TaskState.FAILED,
                                error=str(task_res),
                            )
                            execution.task_executions[task_name] = exec_rec
                            any_failed = True

                            # 保存 checkpoint
                            self._create_checkpoint(execution, task_outputs, task_name, str(task_res))

                            if self._auto_recover:
                                if self.on_recovery_needed:
                                    cp = WorkflowCheckpoint.load(self._checkpoint_path)
                                    self.on_recovery_needed(task_name, str(task_res), cp)
                                continue
                            else:
                                with self._lock:
                                    self._transition_state(WorkflowState.WAITING_RECOVERY, execution)
                                if self.on_recovery_needed:
                                    cp = WorkflowCheckpoint.load(self._checkpoint_path)
                                    self.on_recovery_needed(task_name, str(task_res), cp)
                                await self._recovery_event.wait()
                                if self._state == WorkflowState.RUNNING:
                                    # 恢复后重试当前 Task
                                    retry_res = await self._execute_task_async(
                                        task_name, self._nodes[task_name], task_outputs, executor
                                    )
                                    if isinstance(retry_res, Exception):
                                        execution.state = WorkflowState.FAILED
                                        execution.error = str(retry_res)
                                        break
                                    task_res = retry_res
                                else:
                                    break
                        else:
                            exec_rec = task_res
                            execution.task_executions[task_name] = exec_rec

                        if exec_rec.state == TaskState.COMPLETED:
                            task_outputs[task_name] = exec_rec.output
                            task_outputs[f"{task_name}_output"] = exec_rec.output
                            if exec_rec.artifacts:
                                task_outputs.setdefault("_artifacts", []).extend(
                                    exec_rec.artifacts
                                )
                            if self.on_task_complete:
                                self.on_task_complete(task_name, exec_rec)
                        elif exec_rec.state == TaskState.FAILED:
                            any_failed = True
                            # checkpoint + recovery 逻辑已在上面处理

                    if execution.state == WorkflowState.ABORTED:
                        break
                    if execution.state == WorkflowState.FAILED:
                        break
                    if execution.state == WorkflowState.WAITING_RECOVERY:
                        break
                    # 当前层有任务失败 → 中止后续层（DAG 属性：下游依赖上游）
                    if any_failed:
                        # 标记所有未执行任务为 SKIPPED
                        for node_name in set(node.task.name for node in self._nodes.values()) - set(execution.task_executions.keys()):
                            execution.task_executions[node_name] = TaskExecution(
                                task_name=node_name,
                                state=TaskState.SKIPPED,
                            )
                        with self._lock:
                            self._transition_state(WorkflowState.FAILED, execution)
                        break

            # ── 循环条件检查与重复执行 ──────────────────────────────
            # DAG 执行完毕后，检查带有 loop_condition 的节点
            if execution.state not in (
                WorkflowState.ABORTED,
                WorkflowState.FAILED,
                WorkflowState.WAITING_RECOVERY,
            ):
                for node_name, node in self._nodes.items():
                    if node.loop_condition is None or node.loop_max_iterations <= 1:
                        continue
                    task_exec = execution.task_executions.get(node.task.name)
                    if not task_exec or task_exec.state != TaskState.COMPLETED:
                        continue

                    loop_iteration = 1
                    while loop_iteration < node.loop_max_iterations:
                        if node.loop_condition(task_outputs):
                            break

                        # 条件不满足，准备重新执行
                        feedback = (
                            f"[LOOP ITERATION {loop_iteration + 1}"
                            f"/{node.loop_max_iterations}]\n\n"
                            f"The loop condition for task '{node.task.name}' "
                            f"was not satisfied. Previous output:\n\n"
                            f"{task_exec.output[:1500] if task_exec.output else '(no output)'}"
                            f"\n\nPlease adjust your approach to satisfy the condition."
                        )

                        # 向 conversation 注入 feedback（如果 hub 中存在）
                        if self._hub:
                            conv_id = f"{node.agent_id}/{node.task.name}"
                            conv = self._hub.get_conversation(conv_id)
                            if conv:
                                conv.add_user(feedback)
                                # Register-Memory 压缩
                                try:
                                    logs_dir = os.path.join(
                                        os.environ.get(
                                            "AGENT_OUTPUTS_DIR",
                                            os.path.join(
                                                os.path.dirname(
                                                    os.path.dirname(
                                                        os.path.dirname(__file__)
                                                    )
                                                ),
                                                "outputs",
                                            ),
                                        ),
                                        self.name,
                                        "logs",
                                    )
                                    os.makedirs(logs_dir, exist_ok=True)
                                    conv.archive_round(
                                        pass_num=loop_iteration,
                                        out_dir=logs_dir,
                                    )
                                    conv.compact(keep_recent=10)
                                except Exception:
                                    pass

                        # 重新执行 task
                        new_retry_count = task_exec.retry_count + 1
                        ex = await self._execute_task_async(
                            node.task.name, node, task_outputs, executor
                        )
                        if isinstance(ex, Exception):
                            execution.task_executions[node.task.name] = (
                                TaskExecution(
                                    task_name=node.task.name,
                                    state=TaskState.FAILED,
                                    error=str(ex),
                                )
                            )
                            execution.task_executions[
                                node.task.name
                            ].retry_count = new_retry_count
                            execution.error = (
                                f"Task '{node.task.name}' failed during "
                                f"loop iteration {loop_iteration + 1}: {ex}"
                            )
                            with self._lock:
                                self._transition_state(
                                    WorkflowState.FAILED, execution
                                )
                            break

                        execution.task_executions[node.task.name] = ex
                        if ex.state == TaskState.COMPLETED:
                            task_outputs[node.task.name] = ex.output
                            task_outputs[f"{node.task.name}_output"] = ex.output
                        execution.task_executions[
                            node.task.name
                        ].retry_count = new_retry_count
                        task_exec = ex
                        loop_iteration += 1
                    else:
                        # while 未 break → 所有迭代都失败了
                        if execution.state != WorkflowState.FAILED:
                            if not node.loop_condition(task_outputs):
                                execution.error = (
                                    f"Task '{node.task.name}' loop condition "
                                    f"not met after {node.loop_max_iterations} "
                                    f"iterations"
                                )
                                with self._lock:
                                    self._transition_state(
                                        WorkflowState.FAILED, execution
                                    )
                                break

            # ── 全局 review_gate 检查与返工循环 ──────────────────────
            # 所有 DAG 层执行完毕后，检查 review-implement 循环
            if execution.state not in (
                WorkflowState.ABORTED,
                WorkflowState.FAILED,
                WorkflowState.WAITING_RECOVERY,
            ):
                review_changed = True
                while review_changed and execution.state not in (
                    WorkflowState.FAILED,
                    WorkflowState.ABORTED,
                ):
                    # 暂停检查
                    while self._state == WorkflowState.PAUSED:
                        await asyncio.sleep(0.5)
                        if self._state == WorkflowState.ABORTED:
                            execution.state = WorkflowState.ABORTED
                            break
                    if execution.state == WorkflowState.ABORTED:
                        break

                    review_changed = False
                    for task_name, node in self._nodes.items():
                        # abort 检查
                        if self._state == WorkflowState.ABORTED:
                            execution.state = WorkflowState.ABORTED
                            break
                        if not node.review_gate or node.max_passes <= 1:
                            continue

                        task_exec = execution.task_executions.get(task_name)
                        gate_exec = execution.task_executions.get(node.review_gate)
                        if not task_exec or not gate_exec:
                            continue
                        if gate_exec.state != TaskState.COMPLETED:
                            continue
                        if task_exec.state not in (
                            TaskState.COMPLETED,
                            TaskState.FAILED,
                        ):
                            continue

                        passes_done = task_exec.retry_count
                        if passes_done >= node.max_passes:
                            continue

                        # ── 结构化 review 解析 ──────────────────────
                        decision = self._parse_review_decision(gate_exec)
                        if decision is not None:
                            is_approved = decision.approved
                            feedback = decision.feedback
                            severity = decision.severity
                        else:
                            # Fallback: legacy string matching
                            gate_output = (gate_exec.output or "").upper()
                            is_rejected = any(
                                phrase in gate_output
                                for phrase in ["NOT APPROVED", "NOT YET APPROVED"]
                            )
                            is_approved = "APPROVED" in gate_output and not is_rejected
                            feedback = gate_exec.output or "Review found issues"
                            severity = "unknown"

                        needs_rework = not is_approved

                        # Emit review event for frontend visibility
                        self._emit_review_event(
                            task_name=task_name,
                            review_gate=node.review_gate,
                            approved=is_approved,
                            feedback=feedback,
                            severity=severity,
                            pass_num=passes_done + 1,
                            max_passes=node.max_passes,
                        )

                        if not needs_rework:
                            # Review passed — mark as approved and continue
                            gate_exec.state = TaskState.APPROVED
                            continue

                        # Need rework
                        if passes_done >= node.max_passes - 1:
                            # 重跑次数已耗尽，标记为 FAILED
                            execution.error = (
                                f"Review gate for '{task_name}' failed after "
                                f"{node.max_passes} pass(es). Last review: {feedback[:200]}"
                            )
                            with self._lock:
                                self._transition_state(
                                    WorkflowState.FAILED, execution
                                )
                            break

                        # 广播 feedback 到 Hub（free mode 兼容）
                        # 保留 conversation 历史，追加 feedback 作为新消息
                        if self._hub:
                            try:
                                conv_id = f"{node.agent_id}/{task_name}"
                                conv = self._hub.register(conv_id, "")

                                # 收集当前 workspace 中的文件列表
                                workspace_files: list[str] = []
                                try:
                                    _pkg_dir = os.path.dirname(
                                        os.path.dirname(os.path.dirname(__file__))
                                    )
                                    out_dir = os.environ.get(
                                        "AGENT_OUTPUTS_DIR",
                                        os.path.join(_pkg_dir, "outputs"),
                                    )
                                    wf_dir = os.path.join(out_dir, self.name)
                                    if os.path.isdir(wf_dir):
                                        for entry in os.listdir(wf_dir):
                                            fp = os.path.join(wf_dir, entry)
                                            if (
                                                os.path.isfile(fp)
                                                and not entry.startswith(".")
                                                and entry != "versions"
                                            ):
                                                workspace_files.append(entry)
                                except Exception:
                                    pass

                                file_list = (
                                    ", ".join(sorted(workspace_files))
                                    if workspace_files
                                    else "(none)"
                                )

                                # 不清空 conversation，追加 rework 标记和 feedback
                                conv.add_user(
                                    f"[REWORK REQUIRED — Pass {passes_done + 1}"
                                    f"/{node.max_passes}]\n\n"
                                    f"The reviewer '{node.review_gate}' has provided "
                                    f"feedback on your previous implementation.\n\n"
                                    f"Feedback:\n{feedback}\n\n"
                                    f"Files currently in workspace: {file_list}\n\n"
                                    f"Please fix ALL issues listed above. You may use "
                                    f"read_file_range() to check existing files before "
                                    f"making changes."
                                )

                                # ── Register-Memory 压缩 ──
                                # 归档当前轮次的完整 conversation，然后压缩
                                try:
                                    logs_dir = os.path.join(wf_dir, "logs")
                                    conv.archive_round(
                                        pass_num=passes_done,
                                        out_dir=logs_dir,
                                    )
                                    conv.compact(keep_recent=10)
                                except Exception:
                                    pass
                            except Exception:
                                pass

                        # 强制重跑被 review 的 task（implement）
                        task_outputs[task_name] = feedback
                        task_outputs[f"{task_name}_output"] = feedback
                        task_outputs["_review_feedback"] = feedback
                        new_retry_count = task_exec.retry_count + 1
                        ex = await self._execute_task_async(
                            task_name, node, task_outputs, executor
                        )
                        if isinstance(ex, Exception):
                            execution.task_executions[task_name] = (
                                TaskExecution(
                                    task_name=task_name,
                                    state=TaskState.FAILED,
                                    error=str(ex),
                                )
                            )
                            execution.task_executions[
                                task_name
                            ].retry_count = new_retry_count
                            execution.error = (
                                f"Task '{task_name}' failed during "
                                f"rework pass {passes_done + 1}: {ex}"
                            )
                            with self._lock:
                                self._transition_state(
                                    WorkflowState.FAILED, execution
                                )
                            break  # 退出 for 循环，workflow 标记为 FAILED

                        execution.task_executions[task_name] = ex
                        if ex.state == TaskState.COMPLETED:
                            task_outputs[task_name] = ex.output
                            task_outputs[f"{task_name}_output"] = (
                                ex.output
                            )
                        execution.task_executions[
                            task_name
                        ].retry_count = new_retry_count
                        review_changed = True

                        # review task 也需要重新执行（implement 改了）
                        review_node = self._nodes.get(
                            node.review_gate
                        )
                        if review_node:
                            review_ex = await self._execute_task_async(
                                node.review_gate,
                                review_node,
                                task_outputs,
                                executor,
                            )
                            if isinstance(review_ex, Exception):
                                execution.task_executions[
                                    node.review_gate
                                ] = TaskExecution(
                                    task_name=node.review_gate,
                                    state=TaskState.FAILED,
                                    error=str(review_ex),
                                )
                            else:
                                execution.task_executions[
                                    node.review_gate
                                ] = review_ex
                                if (
                                    review_ex.state
                                    == TaskState.COMPLETED
                                ):
                                    task_outputs[
                                        node.review_gate
                                    ] = review_ex.output
                                    task_outputs[
                                        f"{node.review_gate}_output"
                                    ] = review_ex.output

            # 完成
            if execution.state not in (
                WorkflowState.ABORTED,
                WorkflowState.FAILED,
                WorkflowState.WAITING_RECOVERY,
            ):
                with self._lock:
                    self._transition_state(WorkflowState.COMPLETED, execution)
                if os.path.exists(self._checkpoint_path):
                    os.remove(self._checkpoint_path)

        except Exception as e:
            with self._lock:
                self._transition_state(WorkflowState.FAILED, execution)
                execution.error = str(e)

        finally:
            executor.shutdown(wait=True)
            execution.completed_at = time.time()
            execution.total_elapsed = (execution.completed_at or 0) - (execution.started_at or 0)
            result.total_elapsed = execution.total_elapsed
            result.success = execution.state == WorkflowState.COMPLETED

            # 填充兼容层结果
            for name, ex in execution.task_executions.items():
                result.task_results[name] = TaskResult(
                    task_name=name,
                    success=ex.state == TaskState.COMPLETED,
                    output=ex.output,
                    agent_id=ex.agent_id,
                    elapsed=ex.elapsed,
                    error=ex.error,
                    state=ex.state,
                    artifacts=ex.artifacts,
                )

            if self.on_state_change:
                self.on_state_change(execution.state)
            if self.on_complete:
                self.on_complete(execution)

        return result

    async def _execute_task_async(
        self,
        task_name: str,
        node: Node,
        outputs: dict[str, Any],
        executor: ThreadPoolExecutor,
    ) -> TaskExecution:
        """在线程池中执行单个 Task（含重试、审批、超时、温度）。"""
        # 本地执行器路径
        if node.local_executor is not None:
            return self._execute_local(task_name, node, outputs)

        # Agent + LLM 路径 — 自动重试
        max_retries = node.max_retries
        last_error = None

        for attempt in range(max_retries + 1):
            exec_rec = await self._execute_agent_task(task_name, node, outputs, executor)
            exec_rec.retry_count = attempt

            if exec_rec.state == TaskState.COMPLETED:
                return exec_rec

            last_error = exec_rec.error
            if attempt < max_retries:
                await asyncio.sleep(node.retry_delay)

        # 全部重试失败
        exec_rec.error = f"{last_error} (failed after {max_retries + 1} attempts)"
        return exec_rec

    def _execute_local(
        self,
        task_name: str,
        node: Node,
        outputs: dict[str, Any],
    ) -> TaskExecution:
        """本地执行器路径（不经过 LLM）。"""
        exec_rec = TaskExecution(
            task_name=task_name,
            state=TaskState.RUNNING,
            agent_id=node.agent_id,
            started_at=time.time(),
        )
        # 立即记录到 execution，让前端能获取到 running 状态
        if self._current_execution:
            self._current_execution.task_executions[task_name] = exec_rec
        if self.on_task_start:
            self.on_task_start(task_name, node)

        try:
            result = node.local_executor(outputs)
            exec_rec.state = TaskState.COMPLETED
            exec_rec.output = result
            exec_rec.elapsed = time.time() - (exec_rec.started_at or time.time())
            # 本地执行器可以通过返回值约定传递产物
            if isinstance(result, dict) and "_artifacts" in result:
                exec_rec.artifacts = result["_artifacts"]
        except Exception as e:
            exec_rec.state = TaskState.FAILED
            exec_rec.error = str(e)
            exec_rec.elapsed = time.time() - (exec_rec.started_at or time.time())

        return exec_rec

    async def _execute_agent_task(
        self,
        task_name: str,
        node: Node,
        outputs: dict[str, Any],
        executor: ThreadPoolExecutor,
    ) -> TaskExecution:
        """Agent + LLM 路径（含审批、超时、温度、上下文隔离）。"""
        agent = self._agents.get(node.agent_id)
        exec_rec = TaskExecution(
            task_name=task_name,
            state=TaskState.RUNNING,
            agent_id=node.agent_id,
            started_at=time.time(),
        )
        # 立即记录到 execution，让前端能获取到 running 状态
        if self._current_execution:
            self._current_execution.task_executions[task_name] = exec_rec

        if not agent:
            exec_rec.state = TaskState.FAILED
            exec_rec.error = f"Agent '{node.agent_id}' not found"
            return exec_rec

        if self.on_task_start:
            self.on_task_start(task_name, node)

        # 人工审批
        if node.requires_approval:
            approval_result = await self._wait_for_approval(task_name, node, exec_rec)
            if approval_result == "skip":
                exec_rec.state = TaskState.SKIPPED
                return exec_rec

        # 渲染 Task 描述
        rendered = node.task.render_description(**outputs)

        # 注入上游任务的文本输出（让下游任务能看到之前任务的产出）
        prev_outputs: list[str] = []
        for key, value in outputs.items():
            if key.startswith("_") or key == task_name or key == f"{task_name}_output":
                continue
            if not key.endswith("_output"):
                continue
            if isinstance(value, str) and value.strip():
                source_task = key[:-7]  # 去掉 "_output"
                # 截断过长的输出，避免下游 prompt 爆炸
                MAX_PREV_OUTPUT = 2000
                text = value.strip()
                if len(text) > MAX_PREV_OUTPUT:
                    text = text[:MAX_PREV_OUTPUT] + f"\n\n...[truncated, total {len(value)} chars]"
                prev_outputs.append(f"### Output from '{source_task}'\n{text}")
        if prev_outputs:
            outputs_section = "\n\n".join(prev_outputs)
            rendered = (
                f"[Previously completed tasks]\n\n"
                f"{outputs_section}\n\n"
                f"--- YOUR TASK ---\n\n"
                f"{rendered}"
            )

        # 收集之前的产物信息（通过 outputs 字典）
        previous_artifacts = self._artifact_collector.collect(outputs)
        if previous_artifacts:
            rendered = (
                f"{rendered}\n\n"
                f"[Previously completed tasks produced these files]\n"
                f"{previous_artifacts}"
            )

        try:
            # 每个 Task 独立 Conversation — 关键设计
            conv_id = f"{node.agent_id}/{task_name}"
            if self._hub:
                # 通过 Hub 注册，复用其 Conversation（携带 observer，前端可监控）
                conv = self._hub.register(conv_id, agent.system_prompt)
                # 清理上次失败遗留的未闭合 tool_calls（否则 API 400）
                self._cleanup_dangling_tool_calls(conv)
                if not any(m.role == "system" for m in conv.get_messages()):
                    conv.add_system(agent.system_prompt)
            else:
                conv = Conversation(session_id=conv_id)
                conv.add_system(agent.system_prompt)

            # 设置 spawn_sub_agent 工具
            self._setup_sub_agent(agent)

            # 如果当前 task 是某个 review_gate，注册 review_decision 工具
            is_reviewer = any(
                n.review_gate == task_name for n in self._nodes.values()
            )
            if is_reviewer:
                agent.register_tool(review_decision_tool())
                # 追加 reviewer prompt（不覆盖原有 prompt）
                if "review_decision" not in (agent.system_prompt or ""):
                    agent.system_prompt = (
                        (agent.system_prompt or "") + "\n\n" +
                        reviewer_system_prompt()
                    )

            # Task 级温度控制
            original_temp = None
            if node.temperature is not None:
                original_temp = agent.config.temperature
                agent.config.temperature = node.temperature

            # Task 级工具限制 —— 防止 design 等任务使用不应有的工具
            original_tools: dict[str, Any] = {}
            original_allowed: list[str] | None = None
            if node.allowed_tools is not None:
                original_allowed = agent.config.allowed_tools
                agent.config.allowed_tools = node.allowed_tools
                original_tools = dict(agent._tools)
                agent._tools = {}
                for name, tool in original_tools.items():
                    agent.register_tool(tool)

            try:
                # 在线程池中执行（支持真实 Task 级超时）
                loop = asyncio.get_running_loop()
                original_llm_timeout = None
                if node.timeout is not None:
                    original_llm_timeout = getattr(agent.llm, "timeout", None)
                    agent.llm.timeout = node.timeout
                # 自动化验证层（P1）：review task 执行前自动验证上游产物
                if is_reviewer:
                    auto_validation = self._auto_validate_upstream(task_name)
                    if auto_validation:
                        rendered = (
                            f"[Automated Validation Results]\n\n"
                            f"{auto_validation}\n\n"
                            f"--- YOUR REVIEW TASK ---\n\n"
                            f"{rendered}"
                        )

                try:
                    if node.timeout is not None:
                        agent_result = await asyncio.wait_for(
                            loop.run_in_executor(executor, agent.run, rendered, conv),
                            timeout=node.timeout,
                        )
                    else:
                        agent_result = await loop.run_in_executor(
                            executor, agent.run, rendered, conv
                        )
                except RuntimeError as re_err:
                    if "cannot schedule new futures after shutdown" in str(re_err):
                        # executor 被提前关闭，创建临时 executor 重试
                        fallback = ThreadPoolExecutor(max_workers=2)
                        try:
                            if node.timeout is not None:
                                agent_result = await asyncio.wait_for(
                                    loop.run_in_executor(fallback, agent.run, rendered, conv),
                                    timeout=node.timeout,
                                )
                            else:
                                agent_result = await loop.run_in_executor(
                                    fallback, agent.run, rendered, conv
                                )
                        finally:
                            fallback.shutdown(wait=False)
                    else:
                        raise
                finally:
                    if original_llm_timeout is not None:
                        agent.llm.timeout = original_llm_timeout
            finally:
                # 恢复原始工具
                if node.allowed_tools is not None:
                    agent.config.allowed_tools = original_allowed
                    agent._tools = original_tools
                # 恢复原始温度
                if original_temp is not None:
                    agent.config.temperature = original_temp

            exec_rec.state = TaskState.COMPLETED if agent_result.success else TaskState.FAILED
            exec_rec.output = agent_result.output
            exec_rec.elapsed = time.time() - (exec_rec.started_at or time.time())

            # 将 Agent 的 stop_reason 映射为 error，便于前端展示
            if not agent_result.success and agent_result.stop_reason:
                exec_rec.error = agent_result.stop_reason

            # 从 AgentResult 提取产物信息
            # file_tools 返回的路径是相对于 workspace（outputs/{workflow_name}/）的，
            # 需加上 workflow name 前缀，转为相对于 OUTPUTS_DIR 的路径
            if hasattr(agent_result, "artifacts") and agent_result.artifacts:
                converted = []
                for art in agent_result.artifacts:
                    if not os.path.isabs(art):
                        converted.append(f"{self.name}/{art}".replace("\\", "/"))
                    else:
                        converted.append(art)
                exec_rec.artifacts = converted

            # 自动保存任务输出
            # design 任务保存到 workspace 根目录（作为产物）
            # 其他任务保存到 logs/ 子目录（作为日志）
            if agent_result.success and agent_result.output:
                try:
                    _pkg_dir = os.path.dirname(
                        os.path.dirname(os.path.dirname(__file__))
                    )
                    out_dir = os.environ.get(
                        "AGENT_OUTPUTS_DIR", os.path.join(_pkg_dir, "outputs")
                    )
                    wf_dir = os.path.join(out_dir, self.name)
                    if task_name == "design":
                        # design.md 作为产物放在 workspace 根目录
                        out_path = os.path.join(wf_dir, f"{task_name}.md")
                    else:
                        logs_dir = os.path.join(wf_dir, "logs")
                        os.makedirs(logs_dir, exist_ok=True)
                        out_path = os.path.join(logs_dir, f"{task_name}.md")
                    with open(out_path, "w", encoding="utf-8") as f:
                        f.write(agent_result.output)
                except Exception:
                    pass

            # 保存原始 AgentResult 供 review_gate 解析 review_decision
            exec_rec._raw_result = getattr(agent_result, "raw", None) or agent_result.__dict__

        except TimeoutError as e:
            exec_rec.state = TaskState.FAILED
            exec_rec.error = f"Timeout: {e}"
            exec_rec.elapsed = time.time() - (exec_rec.started_at or time.time())
        except Exception as e:
            exec_rec.state = TaskState.FAILED
            exec_rec.error = str(e)
            exec_rec.elapsed = time.time() - (exec_rec.started_at or time.time())

        if self.on_task_end:
            self.on_task_end(task_name, exec_rec)

        return exec_rec

    # _run_agent_with_timeout 已内联到 _execute_agent_task，使用 asyncio.wait_for
    # 实现真正的 Task 级超时控制（而非仅修改 HTTP 层 timeout）

    async def _wait_for_approval(
        self,
        task_name: str,
        node: Node,
        exec_rec: TaskExecution,
    ) -> str:
        """等待人工审批（async，不阻塞事件循环）。"""
        with self._lock:
            self._transition_state(WorkflowState.WAITING_APPROVAL, self._current_execution)

        if self.on_approval_needed:
            self.on_approval_needed(task_name, node)

        approval_event = asyncio.Event()
        self._approval_events[task_name] = approval_event
        await approval_event.wait()

        if exec_rec.state == TaskState.REJECTED:
            return "skip"
        return "proceed"

    def _create_checkpoint(
        self,
        execution: WorkflowExecution,
        outputs: dict[str, Any],
        failed_task: str,
        error: str | None,
    ) -> None:
        """创建断点 checkpoint。"""
        cp = WorkflowCheckpoint.create(
            workflow_name=self.name,
            workflow_id=self.workflow_id,
            completed_tasks=dict(execution.task_executions),
            task_outputs=dict(outputs),
            failed_task=failed_task,
            failure_reason=error,
        )
        cp.save(self._checkpoint_path)
        if self.on_checkpoint:
            self.on_checkpoint(self._checkpoint_path)

    @staticmethod
    def _cleanup_dangling_tool_calls(conv: Conversation) -> None:
        """清理 conversation 中未闭合的 tool_calls（上次失败遗留）。

        API 要求：assistant 消息含 tool_calls 后必须紧跟对应的 tool 消息。
        如果上次执行被中断（崩溃/取消），会留下不完整的 tool_calls 链，
        下次调用 API 时返回 400。
        """
        from core.llm import Message as LLMMessage

        messages = conv.get_messages()
        msgs_to_keep: list[LLMMessage] = []
        pending_tool_ids: set[str] = set()

        for msg in messages:
            if msg.role == "assistant" and msg.tool_calls:
                # 记录这个 assistant 要求的 tool_call_ids
                for tc in msg.tool_calls:
                    pending_tool_ids.add(tc.id)
                msgs_to_keep.append(msg)
            elif msg.role == "tool" and msg.tool_call_id:
                # tool 消息响应了某个 tool_call
                pending_tool_ids.discard(msg.tool_call_id)
                msgs_to_keep.append(msg)
            else:
                msgs_to_keep.append(msg)

        # 如果最后有未响应的 tool_calls，截断到最后一个完整点
        if pending_tool_ids:
            # 找最后一个 tool 消息的位置，截断到它之后
            last_tool_idx = -1
            for i in range(len(msgs_to_keep) - 1, -1, -1):
                if msgs_to_keep[i].role == "tool" and msgs_to_keep[i].tool_call_id:
                    last_tool_idx = i
                    break

            if last_tool_idx >= 0:
                # 截断：保留到最后一个完整 tool 响应
                cleaned = msgs_to_keep[:last_tool_idx + 1]
            else:
                # 没有 tool 响应 → 回退到 assistant(tool_calls) 之前
                cleaned = []
                for msg in msgs_to_keep:
                    if msg.role == "assistant" and msg.tool_calls:
                        break
                    cleaned.append(msg)

            # 重建 conversation
            conv.clear()
            for msg in cleaned:
                if msg.role == "system":
                    conv.add_system(msg.content or "")
                elif msg.role == "user":
                    conv.add_user(msg.content or "")
                elif msg.role == "assistant":
                    conv.add_assistant(content=msg.content, tool_calls=msg.tool_calls)
                elif msg.role == "tool" and msg.tool_call_id:
                    conv.add_tool_result(msg.tool_call_id, msg.name or "", msg.content or "")

    def _setup_sub_agent(self, agent: Agent) -> None:
        """为 Agent 设置 spawn_sub_agent 工具（按需导入，避免强依赖）。"""
        if not self._hub:
            return
        if any(t.name == "spawn_sub_agent" for t in agent._tools.values()):
            return
        try:
            from core.sub_agent import SubAgentManager
        except Exception:
            return  # sub_agent 模块未安装或不可用
        agent_id = id(agent)
        if agent_id not in self._sub_agent_managers:
            self._sub_agent_managers[agent_id] = SubAgentManager(agent, self._hub)
        manager = self._sub_agent_managers[agent_id]
        agent.register_tool(manager.create_tool())

    # ── 自动化验证层（P1）─────────────────────────────────

    def _auto_validate_upstream(self, review_task_name: str) -> str | None:
        """在 review task 执行前，自动验证上游 task 的产物。

        返回验证报告文本（供注入 review prompt），无产物或验证全通过返回 None。
        """
        # 找到被 review 的上游 task
        reviewed_task_name = None
        for n in self._nodes.values():
            if n.review_gate == review_task_name:
                reviewed_task_name = n.task.name
                break
        if not reviewed_task_name:
            return None

        # 定位 workspace（outputs/{workflow_name}/）
        _pkg_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        out_dir = os.environ.get("AGENT_OUTPUTS_DIR", os.path.join(_pkg_dir, "outputs"))
        workspace = os.path.join(out_dir, self.name)
        if not os.path.isdir(workspace):
            return None

        # 收集 workspace 中的可验证文件（排除 logs/ 目录）
        files_to_check: list[str] = []
        for root, dirs, files in os.walk(workspace):
            # 跳过 logs 目录（避免验证 design.md 等日志）
            dirs[:] = [d for d in dirs if d != "logs"]
            for fname in files:
                if fname.endswith(".html") or fname.endswith(".js"):
                    files_to_check.append(os.path.join(root, fname))

        if not files_to_check:
            return None

        # 运行验证器
        html_v = HtmlValidator()
        js_v = JavaScriptValidator()
        results: list[str] = []
        passed = 0
        failed = 0

        for fpath in files_to_check:
            rel = os.path.relpath(fpath, workspace)
            if fpath.endswith(".html"):
                res = html_v.validate(fpath)
            else:
                res = js_v.validate(fpath)
            status = "PASS" if res.passed else "FAIL"
            if res.passed:
                passed += 1
            else:
                failed += 1
            results.append(f"  [{status}] {rel}: {res.message}")

        header = f"Automated validation: {passed} passed, {failed} failed ({len(files_to_check)} files checked)"
        if failed == 0:
            return f"{header}\n" + "\n".join(results)
        return f"{header}\nIMPORTANT: Fix these issues before submitting your review.\n" + "\n".join(results)

    # ── Review Gate 辅助方法 ──────────────────────────────

    def _parse_review_decision(
        self,
        gate_exec: TaskExecution,
    ) -> ReviewDecision | None:
        """从 reviewer task 的执行结果中解析结构化的 review decision.

        优先从 AgentResult 的 artifacts/output 中查找 _review_decision 字段。
        回退到全局存储（review_decision_tool 写入）。
        """
        # 1. 尝试从 raw AgentResult 中解析（如果 task 执行保留了原始结果）
        raw = getattr(gate_exec, "_raw_result", None)
        if raw and isinstance(raw, dict):
            rd = raw.get("_review_decision")
            if rd:
                return ReviewDecision.from_tool_result(rd)

        # 2. 尝试从 output 字符串中解析 JSON
        if gate_exec.output:
            try:
                import json as _json
                data = _json.loads(gate_exec.output)
                if isinstance(data, dict) and "_review_decision" in data:
                    return ReviewDecision.from_tool_result(data["_review_decision"])
                if isinstance(data, dict) and "approved" in data:
                    return ReviewDecision.from_tool_result(data)
            except Exception:
                pass

        # 3. 回退到全局存储
        return get_review_decision(gate_exec.task_name)

    def _emit_review_event(
        self,
        task_name: str,
        review_gate: str,
        approved: bool,
        feedback: str,
        severity: str,
        pass_num: int,
        max_passes: int,
    ) -> None:
        """发射 review 事件供前端监控。"""
        if self.on_task_end:
            # 复用 on_task_end 钩子，但包装 review 信息
            pass
        # 通过 on_state_change 发射 review 状态变更
        if self.on_state_change:
            # 这里不转换状态，只通知前端
            pass

    # ── 拓扑分层算法 ──────────────────────────────────────

    def _topological_layers(self) -> list[list[str]]:
        """
        Kahn 算法变种 — 每次处理所有入度为 0 的节点为一层。
        每层内的 Task 没有相互依赖，可以安全并行。
        """
        in_degree = dict(self._indegree)
        layers: list[list[str]] = []

        while True:
            current_layer = [n for n, d in in_degree.items() if d == 0]
            if not current_layer:
                break

            layers.append(current_layer)

            for node in current_layer:
                in_degree[node] = -1  # 标记为已处理
                for neighbor in self._edges.get(node, []):
                    in_degree[neighbor] -= 1

        unprocessed = [n for n, d in in_degree.items() if d >= 0]
        if unprocessed:
            raise ValueError(
                f"Workflow contains a cycle, cannot execute. Unprocessed: {unprocessed}"
            )

        return layers

    def _topological_sort(self) -> list[str]:
        """Kahn 算法 — 返回线性顺序。"""
        in_degree = dict(self._indegree)
        queue = deque([n for n, d in in_degree.items() if d == 0])
        order: list[str] = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for neighbor in self._edges.get(node, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(self._nodes):
            raise ValueError("Workflow contains a cycle, cannot execute")

        return order

    # ── 控制接口 ──────────────────────────────────────────

    def approve_task(self, task_name: str) -> bool:
        """审批通过指定 Task。"""
        if task_name not in self._approval_events:
            return False
        exec_rec = self._current_execution.task_executions.get(task_name)
        if exec_rec:
            exec_rec.state = TaskState.APPROVED
        self._approval_events[task_name].set()
        return True

    def reject_task(self, task_name: str) -> bool:
        """拒绝指定 Task。"""
        if task_name not in self._approval_events:
            return False
        exec_rec = self._current_execution.task_executions.get(task_name)
        if exec_rec:
            exec_rec.state = TaskState.REJECTED
        self._approval_events[task_name].set()
        return True

    def resume_from_recovery(self) -> bool:
        """从 WAITING_RECOVERY 状态恢复执行。"""
        with self._lock:
            if self._state != WorkflowState.WAITING_RECOVERY:
                return False
            self._transition_state(WorkflowState.RUNNING, self._current_execution)
        self._recovery_event.set()
        return True

    def pause(self) -> None:
        with self._lock:
            if self._state in (WorkflowState.RUNNING, WorkflowState.PENDING):
                self._transition_state(
                    WorkflowState.PAUSED, self._current_execution
                )

    def resume_from_pause(self) -> None:
        """从 PAUSED 状态恢复为 RUNNING。"""
        with self._lock:
            if self._state == WorkflowState.PAUSED:
                self._transition_state(
                    WorkflowState.RUNNING, self._current_execution
                )

    def abort(self) -> None:
        with self._lock:
            self._transition_state(
                WorkflowState.ABORTED, self._current_execution
            )
        for event in self._approval_events.values():
            event.set()
        self._recovery_event.set()

    @property
    def state(self) -> WorkflowState:
        return self._state

    # ── 可视化 ────────────────────────────────────────────

    def to_mermaid(self) -> str:
        """生成 Mermaid 图语法。"""
        lines = ["graph TD"]
        for task_name in self._nodes:
            safe_name = task_name.replace("-", "_")
            lines.append(f"    {safe_name}[{task_name}]")

        for from_task, to_list in self._edges.items():
            from_safe = from_task.replace("-", "_")
            for to_task in to_list:
                to_safe = to_task.replace("-", "_")
                label = ""
                if (from_task, to_task) in self._edge_conditions:
                    label = '|condition|'
                lines.append(f"    {from_safe} --> {label} {to_safe}")

        return "\n".join(lines)

    # ── 查询 ──────────────────────────────────────────────

    def list_tasks(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "agent_id": n.agent_id,
                "requires_approval": n.requires_approval,
                "timeout": n.timeout,
                "max_retries": n.max_retries,
                "temperature": n.temperature,
                "parallel": n.parallel,
                "has_local_executor": n.local_executor is not None,
                "review_gate": n.review_gate,
                "max_passes": n.max_passes,
            }
            for name, n in self._nodes.items()
        ]

    def get_checkpoint_path(self) -> str:
        return self._checkpoint_path

    def has_checkpoint(self) -> bool:
        return os.path.exists(self._checkpoint_path)

    def __repr__(self) -> str:
        return f"WorkflowEngine(name='{self.name}', tasks={list(self._nodes.keys())})"
