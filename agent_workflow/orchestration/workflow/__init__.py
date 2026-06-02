"""
Workflow 合并模块 — DAG 表达能力 + V2 生产特性。

统一入口，向后兼容。
"""
from orchestration.workflow.state import (
    TaskExecution,
    TaskState,
    WorkflowExecution,
    WorkflowState,
)
from orchestration.workflow.checkpoint import WorkflowCheckpoint
from orchestration.workflow.engine import (
    ArtifactCollector,
    Node,
    TaskResult,
    WorkflowEngine,
    WorkflowResult,
)
from orchestration.workflow.presets import (
    conditional_workflow,
    mapreduce_workflow,
    parallel_workflow,
    run_chain,
    sequential_workflow,
)

# 向后兼容别名
Workflow = WorkflowEngine

__all__ = [
    # 状态机
    "WorkflowState",
    "TaskState",
    "TaskExecution",
    "WorkflowExecution",
    # 断点
    "WorkflowCheckpoint",
    # 引擎
    "WorkflowEngine",
    "Workflow",  # 别名
    "Node",
    "TaskResult",
    "WorkflowResult",
    "ArtifactCollector",
    # 预设
    "sequential_workflow",
    "parallel_workflow",
    "mapreduce_workflow",
    "conditional_workflow",
    "run_chain",
]
