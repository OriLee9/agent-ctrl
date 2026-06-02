"""
Workflow 状态机 — WorkflowState/TaskState 枚举 + TaskExecution 记录。

设计原则:
- 状态枚举是自解释的，不依赖外部上下文
- TaskExecution 是可序列化的纯数据对象
- 支持 to_dict/from_dict 用于 Checkpoint 持久化
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WorkflowState(Enum):
    """Workflow 的整体执行状态。"""

    PENDING = "pending"               # 尚未开始
    RUNNING = "running"               # 正在执行
    PAUSED = "paused"                 # 人工暂停
    WAITING_APPROVAL = "waiting_approval"     # 等待人工审批
    WAITING_RECOVERY = "waiting_recovery"     # 等待断点恢复
    COMPLETED = "completed"           # 全部成功完成
    FAILED = "failed"                 # 执行失败且无法恢复
    ABORTED = "aborted"               # 人工终止


class TaskState(Enum):
    """单个 Task 的执行状态。"""

    PENDING = "pending"               # 等待执行
    RUNNING = "running"               # 正在执行
    WAITING_APPROVAL = "waiting_approval"     # 等待审批
    APPROVED = "approved"             # 审批通过
    REJECTED = "rejected"             # 审批拒绝
    COMPLETED = "completed"           # 执行成功
    FAILED = "failed"                 # 执行失败
    SKIPPED = "skipped"               # 条件不满足被跳过
    RECOVERED = "recovered"           # 断点恢复后重试成功


@dataclass
class TaskExecution:
    """单个 Task 的完整执行记录（可序列化）。"""

    task_name: str
    state: TaskState = TaskState.PENDING
    output: str = ""
    agent_id: str = ""
    elapsed: float = 0.0
    started_at: float | None = None
    completed_at: float | None = None
    error: str | None = None
    retry_count: int = 0
    # 扩展：存储 Task 产出的文件路径列表（替代硬编码目录扫描）
    artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_name": self.task_name,
            "state": self.state.value,
            "output": self.output,
            "agent_id": self.agent_id,
            "elapsed": self.elapsed,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "retry_count": self.retry_count,
            "artifacts": self.artifacts,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskExecution":
        return cls(
            task_name=data["task_name"],
            state=TaskState(data.get("state", "pending")),
            output=data.get("output", ""),
            agent_id=data.get("agent_id", ""),
            elapsed=data.get("elapsed", 0.0),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            error=data.get("error"),
            retry_count=data.get("retry_count", 0),
            artifacts=data.get("artifacts", []),
        )


@dataclass
class WorkflowExecution:
    """Workflow 的完整执行记录（可序列化）。"""

    workflow_id: str
    state: WorkflowState = WorkflowState.PENDING
    task_executions: dict[str, TaskExecution] = field(default_factory=dict)
    current_task: str | None = None
    total_elapsed: float = 0.0
    started_at: float | None = None
    completed_at: float | None = None
    error: str | None = None
    checkpoint_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "state": self.state.value,
            "task_executions": {
                name: ex.to_dict()
                for name, ex in self.task_executions.items()
            },
            "current_task": self.current_task,
            "total_elapsed": self.total_elapsed,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "checkpoint_path": self.checkpoint_path,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowExecution":
        ex = cls(
            workflow_id=data["workflow_id"],
            state=WorkflowState(data.get("state", "pending")),
            current_task=data.get("current_task"),
            total_elapsed=data.get("total_elapsed", 0.0),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
            error=data.get("error"),
            checkpoint_path=data.get("checkpoint_path"),
        )
        for name, te_data in data.get("task_executions", {}).items():
            ex.task_executions[name] = TaskExecution.from_dict(te_data)
        return ex
