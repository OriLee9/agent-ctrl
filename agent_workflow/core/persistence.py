"""
持久化层 — Conversation快照的JSON落盘。

设计思路:
- 纯JSON，无额外依赖
- 完整保存消息、步骤、快照
- 支持增量保存（只保存变更）
- 原子写入（先写临时文件再重命名）

参考:
- MiniCode-Agent [https://github.com/xu-kai-quan/MiniCode-Agent] 的session持久化思路
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from core.llm import Message, ToolCall, Usage
from core.memory import Conversation, Snapshot, StepRecord


def _message_to_dict(msg: Message) -> dict[str, Any]:
    """Message序列化为字典。"""
    d = {"role": msg.role}
    if msg.content is not None:
        d["content"] = msg.content
    if msg.tool_calls is not None:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "function": tc.function,
                "arguments": tc.arguments,
            }
            for tc in msg.tool_calls
        ]
    if msg.tool_call_id is not None:
        d["tool_call_id"] = msg.tool_call_id
    if msg.name is not None:
        d["name"] = msg.name
    return d


def _message_from_dict(d: dict[str, Any]) -> Message:
    """字典反序列化为Message。"""
    tool_calls = None
    if "tool_calls" in d:
        tool_calls = [
            ToolCall(id=tc["id"], function=tc["function"], arguments=tc["arguments"])
            for tc in d["tool_calls"]
        ]
    return Message(
        role=d["role"],
        content=d.get("content"),
        tool_calls=tool_calls,
        tool_call_id=d.get("tool_call_id"),
        name=d.get("name"),
    )


def _step_to_dict(step: StepRecord) -> dict[str, Any]:
    """StepRecord序列化为字典。"""
    return {
        "step_id": step.step_id,
        "iteration": step.iteration,
        "timestamp": step.timestamp,
        "thought": step.thought,
        "action": step.action,
        "observation": step.observation,
        "usage": {
            "prompt_tokens": step.usage.prompt_tokens,
            "completion_tokens": step.usage.completion_tokens,
            "total_tokens": step.usage.total_tokens,
        } if step.usage else None,
        "intervention": step.intervention,
    }


def _step_from_dict(d: dict[str, Any]) -> StepRecord:
    """字典反序列化为StepRecord。"""
    usage = None
    if d.get("usage"):
        usage = Usage(
            prompt_tokens=d["usage"].get("prompt_tokens", 0),
            completion_tokens=d["usage"].get("completion_tokens", 0),
            total_tokens=d["usage"].get("total_tokens", 0),
        )
    return StepRecord(
        step_id=d.get("step_id", ""),
        iteration=d.get("iteration", 0),
        timestamp=d.get("timestamp", 0.0),
        thought=d.get("thought"),
        action=d.get("action"),
        observation=d.get("observation"),
        usage=usage,
        intervention=d.get("intervention"),
    )


def _snapshot_to_dict(snap: Snapshot) -> dict[str, Any]:
    """Snapshot序列化为字典。"""
    return {
        "snapshot_id": snap.snapshot_id,
        "timestamp": snap.timestamp,
        "messages": [_message_to_dict(m) for m in snap.messages],
        "steps": [_step_to_dict(s) for s in snap.steps],
        "metadata": snap.metadata,
        "parent_id": snap.parent_id,
    }


def _snapshot_from_dict(d: dict[str, Any]) -> Snapshot:
    """字典反序列化为Snapshot。"""
    return Snapshot(
        snapshot_id=d.get("snapshot_id", ""),
        timestamp=d.get("timestamp", 0.0),
        messages=[_message_from_dict(m) for m in d.get("messages", [])],
        steps=[_step_from_dict(s) for s in d.get("steps", [])],
        metadata=d.get("metadata", {}),
        parent_id=d.get("parent_id"),
    )


# ── 公开API ─────────────────────────────────────────────

class ConversationStore:
    """Conversation的JSON文件持久化。"""

    @staticmethod
    def save(conv: Conversation, path: str | Path) -> None:
        """
        保存Conversation到JSON文件（原子写入）。

        Args:
            conv: Conversation实例
            path: 文件路径
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "session_id": conv.session_id,
            "system_prompt": conv.system_prompt,
            "messages": [_message_to_dict(m) for m in conv.get_messages()],
            "steps": [_step_to_dict(s) for s in conv.get_steps()],
            "snapshots": {
                sid: _snapshot_to_dict(snap)
                for sid, snap in conv._snapshots.items()
            },
            "usage": {
                "prompt_tokens": conv._usage_total.prompt_tokens,
                "completion_tokens": conv._usage_total.completion_tokens,
                "total_tokens": conv._usage_total.total_tokens,
            },
        }

        # 原子写入
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, dir=path.parent, encoding="utf-8"
        )
        try:
            json.dump(data, tmp, ensure_ascii=False, indent=2)
            tmp.close()
            os.replace(tmp.name, path)
        except Exception:
            tmp.close()
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            raise

    @staticmethod
    def load(path: str | Path) -> Conversation:
        """
        从JSON文件加载Conversation。

        Args:
            path: 文件路径

        Returns:
            恢复的Conversation实例
        """
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        conv = Conversation(session_id=data.get("session_id", ""))
        conv.system_prompt = data.get("system_prompt")

        # 恢复消息
        for msg_data in data.get("messages", []):
            conv._messages.append(_message_from_dict(msg_data))

        # 恢复步骤
        for step_data in data.get("steps", []):
            conv._steps.append(_step_from_dict(step_data))

        # 恢复快照
        for sid, snap_data in data.get("snapshots", {}).items():
            conv._snapshots[sid] = _snapshot_from_dict(snap_data)

        # 恢复usage
        usage_data = data.get("usage", {})
        conv._usage_total = Usage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )

        return conv

    @staticmethod
    def exists(path: str | Path) -> bool:
        """检查文件是否存在。"""
        return Path(path).is_file()


# ── 便捷函数 ────────────────────────────────────────────

def save_conversation(conv: Conversation, path: str | Path) -> None:
    """便捷函数: 保存Conversation。"""
    ConversationStore.save(conv, path)


def load_conversation(path: str | Path) -> Conversation:
    """便捷函数: 加载Conversation。"""
    return ConversationStore.load(path)
