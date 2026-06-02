"""
Workflow — 向后兼容别名，指向合并后的 WorkflowEngine。

原 workflow.py（DAG 拓扑并行）和 workflow_v2.py（固定链 + 断点续跑）
已合并为 workflow/engine.py 中的 WorkflowEngine。

此文件保留向后兼容性：
    from orchestration.workflow import Workflow  # 同以前
    # 等价于
    from orchestration.workflow.engine import WorkflowEngine as Workflow
"""
from orchestration.workflow.engine import (
    ArtifactCollector,
    Node,
    TaskResult,
    WorkflowEngine,
    WorkflowResult,
)
from orchestration.workflow.state import (
    TaskExecution,
    TaskState,
    WorkflowExecution,
    WorkflowState,
)

# 向后兼容别名
Workflow = WorkflowEngine

__all__ = [
    "WorkflowState",
    "TaskState",
    "TaskExecution",
    "WorkflowExecution",
    "Workflow",
    "WorkflowEngine",
    "Node",
    "TaskResult",
    "WorkflowResult",
    "ArtifactCollector",
]
