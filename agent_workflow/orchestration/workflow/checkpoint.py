"""
Workflow 断点续跑 — Checkpoint 的序列化/反序列化。

设计原则:
- 纯数据，无业务逻辑
- JSON 格式，人类可读，可手动编辑修复
- 包含恢复所需的全部状态（已完成 Task + 失败 Task + 输出字典）
- artifacts 通过 outputs 字典传递，不硬编码业务路径
"""
from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from orchestration.workflow.state import TaskExecution, TaskState


@dataclass
class WorkflowCheckpoint:
    """断点检查点 — 可序列化保存到文件。"""

    checkpoint_id: str
    workflow_name: str
    workflow_id: str
    timestamp: float
    # 已完成 Task 的执行记录
    completed_tasks: dict[str, TaskExecution] = field(default_factory=dict)
    # Task 输出（用于模板变量和产物传递）
    task_outputs: dict[str, Any] = field(default_factory=dict)
    # 失败的 Task 名（恢复时从这里继续）
    failed_task: str | None = None
    # 失败原因
    failure_reason: str | None = None
    # 已重试次数
    retry_count: int = 0

    def save(self, path: str) -> None:
        """保存 checkpoint 到 JSON 文件。"""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {
            "checkpoint_id": self.checkpoint_id,
            "workflow_name": self.workflow_name,
            "workflow_id": self.workflow_id,
            "timestamp": self.timestamp,
            "completed_tasks": {
                name: ex.to_dict()
                for name, ex in self.completed_tasks.items()
            },
            "task_outputs": self.task_outputs,
            "failed_task": self.failed_task,
            "failure_reason": self.failure_reason,
            "retry_count": self.retry_count,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: str) -> "WorkflowCheckpoint | None":
        """从 JSON 文件加载 checkpoint。"""
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        cp = cls(
            checkpoint_id=data["checkpoint_id"],
            workflow_name=data["workflow_name"],
            workflow_id=data["workflow_id"],
            timestamp=data["timestamp"],
            task_outputs=data.get("task_outputs", {}),
            failed_task=data.get("failed_task"),
            failure_reason=data.get("failure_reason"),
            retry_count=data.get("retry_count", 0),
        )
        # 恢复 completed_tasks
        for name, exec_data in data.get("completed_tasks", {}).items():
            cp.completed_tasks[name] = TaskExecution.from_dict(exec_data)
        return cp

    @classmethod
    def create(
        cls,
        workflow_name: str,
        workflow_id: str,
        completed_tasks: dict[str, TaskExecution],
        task_outputs: dict[str, Any],
        failed_task: str | None = None,
        failure_reason: str | None = None,
    ) -> "WorkflowCheckpoint":
        """便捷构造方法。"""
        return cls(
            checkpoint_id=f"cp_{uuid.uuid4().hex[:8]}",
            workflow_name=workflow_name,
            workflow_id=workflow_id,
            timestamp=time.time(),
            completed_tasks=dict(completed_tasks),
            task_outputs=dict(task_outputs),
            failed_task=failed_task,
            failure_reason=failure_reason,
        )
