"""
Memory层 — 上下文存储与快照管理。

设计思路:
- Conversation: 单个Agent的对话上下文，消息 + 元数据 + Token计数
- Snapshot: 不可变的上下文快照，支持回滚
- 所有操作可观察（observer模式），为ContextHub提供监控入口

参考:
- LangChain [https://github.com/langchain-ai/langchain] 的BaseMemory抽象
- MiniCode-Agent [https://github.com/xu-kai-quan/MiniCode-Agent] 的session状态管理

原则:
- 存储是中心化的，不分散在Agent实例中
- 每条消息都有唯一ID，可追踪
- 快照轻量、快速，支持高频操作
"""
from __future__ import annotations

import copy
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from core.llm import Message, Usage

# Re-export Usage for backward compatibility
__all__ = ["StepRecord", "Snapshot", "Conversation", "Usage"]


@dataclass
class StepRecord:
    """
    单次执行步骤的完整记录。

    一次 ReAct 循环 = 一个 Step:
    - step_id: 唯一标识
    - iteration: 第几次循环
    - timestamp: 时间戳
    - thought: 模型的思考内容
    - action: 执行的动作（tool_call）
    - observation: 观察结果
    - usage: Token消耗
    """
    step_id: str = field(default_factory=lambda: f"step_{uuid.uuid4().hex[:8]}")
    iteration: int = 0
    timestamp: float = field(default_factory=time.time)
    thought: str | None = None
    action: dict[str, Any] | None = None  # {tool_name, arguments}
    observation: str | None = None
    usage: Usage | None = None
    # 新增：干预标记，用于规则引擎做打断或修改
    intervention: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "iteration": self.iteration,
            "timestamp": self.timestamp,
            "thought": self.thought,
            "action": self.action,
            "observation": self.observation,
            "usage": {
                "prompt_tokens": self.usage.prompt_tokens,
                "completion_tokens": self.usage.completion_tokens,
                "total_tokens": self.usage.total_tokens,
            } if self.usage else None,
            "intervention": self.intervention,
        }


@dataclass
class Snapshot:
    """
    上下文的不可变快照。

    用于:
    - 回滚到历史状态
    - 分支执行（从快照分叉）
    - 持久化检查点
    """
    snapshot_id: str = field(default_factory=lambda: f"snap_{uuid.uuid4().hex[:8]}")
    timestamp: float = field(default_factory=time.time)
    messages: list[Message] = field(default_factory=list)
    steps: list[StepRecord] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    # 父快照ID，形成快照链
    parent_id: str | None = None


@dataclass
class Conversation:
    """
    单个Agent的对话上下文。

    职责:
    1. 消息存储与检索
    2. 执行步骤追踪
    3. 快照创建与恢复
    4. 观察者回调（供外部监控）
    5. Token使用统计

    所有写操作都通过add/remove/clear完成，确保observer可被触发。
    """
    session_id: str = field(default_factory=lambda: f"sess_{uuid.uuid4().hex[:8]}")
    system_prompt: str | None = None

    # 内部状态
    _messages: list[Message] = field(default_factory=list, repr=False)
    _steps: list[StepRecord] = field(default_factory=list, repr=False)
    _snapshots: dict[str, Snapshot] = field(default_factory=dict, repr=False)
    _usage_total: Usage = field(default_factory=lambda: Usage(0, 0, 0), repr=False)
    _observers: list[Callable[[str, dict[str, Any]], None]] = field(default_factory=list, repr=False)

    # ── 消息操作 ──────────────────────────────────────────

    def add(self, message: Message) -> None:
        """添加一条消息，触发observer。"""
        self._messages.append(message)
        self._notify("message_added", {
            "session_id": self.session_id,
            "message": message.to_dict(),
            "index": len(self._messages) - 1,
        })

    def add_system(self, content: str) -> None:
        """设置/更新系统提示。"""
        self.system_prompt = content
        # 如果第一条是system，替换；否则插入开头
        if self._messages and self._messages[0].role == "system":
            self._messages[0] = Message(role="system", content=content)
        else:
            self._messages.insert(0, Message(role="system", content=content))
        self._notify("system_updated", {
            "session_id": self.session_id,
            "content": content,
        })

    def add_user(self, content: str) -> None:
        """添加用户消息。"""
        self.add(Message(role="user", content=content))

    def add_assistant(self, content: str | None = None, tool_calls: list | None = None) -> None:
        """添加助手消息。"""
        self.add(Message(role="assistant", content=content, tool_calls=tool_calls))

    def add_tool_result(self, tool_call_id: str, name: str, result: str) -> None:
        """添加工具执行结果。"""
        self.add(Message(
            role="tool",
            content=result,
            tool_call_id=tool_call_id,
            name=name,
        ))

    def get_messages(self) -> list[Message]:
        """获取当前完整消息列表（只读副本）。"""
        return copy.deepcopy(self._messages)

    def last_message(self) -> Message | None:
        """获取最后一条消息。"""
        if not self._messages:
            return None
        return copy.deepcopy(self._messages[-1])

    # ── 步骤追踪 ──────────────────────────────────────────

    def record_step(self, step: StepRecord) -> None:
        """记录一个执行步骤。"""
        step.iteration = len(self._steps) + 1
        self._steps.append(step)
        if step.usage:
            self._accumulate_usage(step.usage)
        self._notify("step_recorded", {
            "session_id": self.session_id,
            "step": step.to_dict(),
        })

    def get_steps(self) -> list[StepRecord]:
        """获取所有执行步骤。"""
        return copy.deepcopy(self._steps)

    # ── 快照与回滚 ───────────────────────────────────────

    def snapshot(self, metadata: dict[str, Any] | None = None) -> str:
        """
        创建当前上下文的快照，返回snapshot_id。

        可用于后续回滚或分叉执行。
        """
        snap = Snapshot(
            messages=self.get_messages(),
            steps=self.get_steps(),
            metadata=metadata or {},
        )
        self._snapshots[snap.snapshot_id] = snap
        self._notify("snapshot_created", {
            "session_id": self.session_id,
            "snapshot_id": snap.snapshot_id,
            "message_count": len(snap.messages),
            "step_count": len(snap.steps),
        })
        return snap.snapshot_id

    def rollback(self, snapshot_id: str) -> bool:
        """
        回滚到指定快照。

        返回是否成功。
        """
        if snapshot_id not in self._snapshots:
            return False
        snap = self._snapshots[snapshot_id]
        self._messages = copy.deepcopy(snap.messages)
        self._steps = copy.deepcopy(snap.steps)
        self._notify("rollback", {
            "session_id": self.session_id,
            "snapshot_id": snapshot_id,
            "restored_messages": len(self._messages),
            "restored_steps": len(self._steps),
        })
        return True

    def list_snapshots(self) -> list[dict[str, Any]]:
        """列出所有快照信息。"""
        return [
            {
                "snapshot_id": s.snapshot_id,
                "timestamp": s.timestamp,
                "message_count": len(s.messages),
                "step_count": len(s.steps),
                "metadata": s.metadata,
            }
            for s in self._snapshots.values()
        ]

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """删除指定快照。"""
        if snapshot_id in self._snapshots:
            del self._snapshots[snapshot_id]
            return True
        return False

    # ── 统计与查询 ────────────────────────────────────────

    @property
    def message_count(self) -> int:
        return len(self._messages)

    @property
    def step_count(self) -> int:
        return len(self._steps)

    @property
    def total_usage(self) -> Usage:
        return copy.deepcopy(self._usage_total)

    def _accumulate_usage(self, usage: Usage) -> None:
        self._usage_total.prompt_tokens += usage.prompt_tokens
        self._usage_total.completion_tokens += usage.completion_tokens
        self._usage_total.total_tokens += usage.total_tokens

    # ── 观察者与监控 ──────────────────────────────────────

    def add_observer(self, callback: Callable[[str, dict[str, Any]], None]) -> None:
        """
        添加观察者回调。

        callback(event_type: str, data: dict) 会在每次状态变更时被调用:
        - "message_added": 新消息
        - "system_updated": 系统提示更新
        - "step_recorded": 新步骤
        - "snapshot_created": 快照创建
        - "rollback": 回滚操作
        """
        self._observers.append(callback)

    def remove_observer(self, callback: Callable[[str, dict[str, Any]], None]) -> None:
        """移除观察者。"""
        if callback in self._observers:
            self._observers.remove(callback)

    def _notify(self, event_type: str, data: dict[str, Any]) -> None:
        """通知所有观察者。"""
        for observer in self._observers:
            try:
                observer(event_type, data)
            except Exception:
                # Observer不应阻塞主流程
                pass

    # ── 实用方法 ──────────────────────────────────────────

    def clear(self) -> None:
        """清空所有消息和步骤（保留snapshots和observers）。"""
        self._messages.clear()
        self._steps.clear()
        self._usage_total = Usage(0, 0, 0)
        self._notify("cleared", {"session_id": self.session_id})

    def summary(self) -> dict[str, Any]:
        """返回当前状态的摘要。"""
        return {
            "session_id": self.session_id,
            "message_count": self.message_count,
            "step_count": self.step_count,
            "total_usage": {
                "prompt_tokens": self._usage_total.prompt_tokens,
                "completion_tokens": self._usage_total.completion_tokens,
                "total_tokens": self._usage_total.total_tokens,
            },
            "snapshots": len(self._snapshots),
            "last_message": self._messages[-1].to_dict() if self._messages else None,
        }

    def to_transcript(self) -> str:
        """
        生成可读的对话记录文本。

        用于调试和日志输出。
        """
        lines: list[str] = [f"=== Conversation: {self.session_id} ==="]
        for msg in self._messages:
            role = msg.role.upper()
            if role == "TOOL":
                lines.append(f"\n--- {role}[{msg.name}] ---")
            else:
                lines.append(f"\n--- {role} ---")
            if msg.content:
                lines.append(msg.content)
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    lines.append(f"[ToolCall] {tc.function}({tc.arguments})")
        return "\n".join(lines)


