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
import os
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

    # ── Conversation Compression (Register-Memory Model) ─────────

    def archive_round(
        self,
        pass_num: int,
        out_dir: str,
    ) -> str:
        """将当前完整对话保存为 JSON 归档文件。

        归档文件供前端读取以显示历史轮次的完整消息。
        当前 conversation（寄存器）随后可通过 compact() 压缩。

        Args:
            pass_num: 当前轮次编号（0=原始, 1=第一次返工, ...）
            out_dir: 归档目录（通常是 logs/）

        Returns:
            归档文件绝对路径
        """
        os.makedirs(out_dir, exist_ok=True)
        filepath = os.path.join(out_dir, f"round_{pass_num}_conversation.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "session_id": self.session_id,
                    "pass_num": pass_num,
                    "timestamp": time.time(),
                    "message_count": len(self._messages),
                    "step_count": len(self._steps),
                    "messages": [m.to_dict() for m in self._messages],
                    "steps": [s.to_dict() for s in self._steps],
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
        return filepath

    def compact(self, keep_recent: int = 10) -> None:
        """压缩 conversation：保留 system + 最近 N 条，中间替换为 [History Archive]。

        遵循 Register-Memory 原则：不重复 IMPLEMENTATION_SUMMARY.md 中已有的
        结构化信息（文件列表、checklist），只提取叙事性内容（reviewer feedback）。

        Args:
            keep_recent: 保留的最近消息数量（默认 10 条）
        """
        if self.message_count <= keep_recent + 1:
            return  # 消息太少，无需压缩

        # system prompt 的位置（通常在第 0 条）
        system_end = 0
        if self._messages and self._messages[0].role == "system":
            system_end = 1

        # 计算截断点：保留 system + 最近 keep_recent 条
        cutoff = max(system_end, self.message_count - keep_recent)
        if cutoff <= system_end:
            return  # 没有可压缩的中间消息

        # ── 关键修复：截断点不能落在 tool 消息上 ──
        # API 要求每条 tool 消息必须有前置的 assistant + tool_calls
        # 如果截断点落在 tool 上，保留段将以孤立的 tool 开头 → 400
        while cutoff > system_end and self._messages[cutoff].role == "tool":
            cutoff -= 1

        # ── 提取旧消息中的 reviewer feedback 要点 ──
        feedback_snippets: list[str] = []
        for msg in self._messages[system_end:cutoff]:
            if msg.role == "user" and msg.content and "[REWORK REQUIRED" in msg.content:
                content = msg.content
                fb_start = content.find("Feedback:\n")
                if fb_start >= 0:
                    fb_text = content[fb_start + len("Feedback:\n"):]
                    fb_end = fb_text.find("\n\nFiles currently")
                    if fb_end >= 0:
                        fb_text = fb_text[:fb_end]
                    fb_text = fb_text.strip()
                    if len(fb_text) > 200:
                        fb_text = fb_text[:200] + "..."
                    if fb_text:
                        feedback_snippets.append(fb_text)

        # ── 构建 [History Archive] 引用消息 ──
        archive_lines = ["[History Archive]"]
        archive_lines.append("")
        archive_lines.append(
            "Previous conversation rounds archived in this directory."
        )
        archive_lines.append(
            "For full implementation details, read IMPLEMENTATION_SUMMARY.md."
        )

        if feedback_snippets:
            archive_lines.append("")
            archive_lines.append("Key reviewer feedback from prior rounds:")
            for i, fb in enumerate(feedback_snippets, 1):
                archive_lines.append(f"  {i}. {fb}")

        archive_content = "\n".join(archive_lines)

        # ── 替换消息列表 ──
        preserved: list[Message] = []
        preserved.extend(self._messages[:system_end])  # system prompt
        preserved.append(Message(role="system", content=archive_content))
        preserved.extend(self._messages[cutoff:])  # 最近 keep_recent 条

        removed_count = self.message_count - len(preserved)
        self._messages = preserved
        self._notify("compacted", {
            "session_id": self.session_id,
            "kept": len(preserved),
            "removed": removed_count,
            "keep_recent": keep_recent,
        })

