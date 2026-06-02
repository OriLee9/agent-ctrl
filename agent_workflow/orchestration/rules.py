"""
规则引擎 — 基于ContextHub事件的自动干预。

设计思路:
- 监听ContextHub的事件流
- 当检测到特定模式时自动触发intervention
- 规则可插拔: 注册自定义检测函数

当前内置规则:
- 重复短句思考检测: 连续N次thought长度<阈值 → pause + intervene

参考:
- AutoGen [https://github.com/microsoft/autogen] 的Human-in-the-loop干预机制
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from orchestration.context_hub import ContextEvent, ContextHub, Intervention


@dataclass
class RuleConfig:
    """规则配置。"""
    # 重复短句检测参数
    max_repeated_short_thoughts: int = 3  # 连续N次触发
    short_thought_threshold: int = 20  # 短句字符阈值
    # 触发后干预内容
    intervention_message: str = (
        "You seem to be stuck in repetitive short thoughts. "
        "Please take a deep breath and approach the problem from a different angle."
    )


class SimpleRuleEngine:
    """
    简单规则引擎。

    使用方式:
        hub = ContextHub()
        engine = SimpleRuleEngine(hub)
        engine.start()  # 开始监听

        # 自动检测并在必要时干预
        # ... Agent运行 ...

        engine.stop()  # 停止监听

    内置规则:
    1. 重复短句思考: 连续3次thought<20字符 → pause + insert干预消息
    """

    def __init__(self, hub: ContextHub, config: RuleConfig | None = None):
        self.hub = hub
        self.config = config or RuleConfig()
        self._running = False
        # 跟踪每个Agent的连续短句计数: {agent_id: count}
        self._short_thought_counts: dict[str, int] = {}
        # 自定义规则: [(name, check_fn, action_fn)]
        self._custom_rules: list[tuple[str, Callable, Callable]] = []

    def start(self) -> None:
        """启动规则引擎，注册事件监听。"""
        if self._running:
            return
        self._running = True
        self.hub.on(ContextEvent.STEP_RECORDED, self._on_step)

    def stop(self) -> None:
        """停止规则引擎。"""
        self._running = False
        # Note: 无法真正移除listener（ContextHub.off支持）

    def add_rule(
        self,
        name: str,
        check: Callable[[str, dict[str, Any], "SimpleRuleEngine"], bool],
        action: Callable[[str, dict[str, Any], "SimpleRuleEngine"], None],
    ) -> None:
        """
        添加自定义规则。

        Args:
            name: 规则名称
            check: (agent_id, step_data, engine) -> bool 检测函数
            action: (agent_id, step_data, engine) -> None 触发函数
        """
        self._custom_rules.append((name, check, action))

    # ── 内置规则: 重复短句检测 ────────────────────────────

    def _on_step(self, data: dict[str, Any]) -> None:
        """STEP_RECORDED事件处理。"""
        if not self._running:
            return

        agent_id = data.get("agent_id")
        step = data.get("step", {})

        if not agent_id or not step:
            return

        # 检查内置规则
        self._check_repeated_short_thoughts(agent_id, step)

        # 检查自定义规则
        for name, check, action in self._custom_rules:
            try:
                if check(agent_id, step, self):
                    action(agent_id, step, self)
            except Exception:
                pass

    def _check_repeated_short_thoughts(self, agent_id: str, step: dict[str, Any]) -> None:
        """检测连续短句思考。"""
        thought = step.get("thought") or ""

        # 判断是否为短句（去除空白后长度）
        is_short = len(thought.strip()) < self.config.short_thought_threshold

        if is_short:
            self._short_thought_counts[agent_id] = self._short_thought_counts.get(agent_id, 0) + 1
        else:
            self._short_thought_counts[agent_id] = 0

        count = self._short_thought_counts.get(agent_id, 0)

        if count >= self.config.max_repeated_short_thoughts:
            # 触发干预
            self._trigger_intervention(agent_id, f"repeated_short_thoughts x{count}")
            # 重置计数，避免连续触发
            self._short_thought_counts[agent_id] = 0

    def _trigger_intervention(self, agent_id: str, reason: str) -> None:
        """触发干预: pause + insert系统消息。"""
        # 1. 暂停Agent
        self.hub.intervene(Intervention(
            type="pause",
            target=agent_id,
            reason=reason,
        ))

        # 2. 插入干预消息
        self.hub.intervene(Intervention(
            type="insert",
            target=agent_id,
            data={"role": "system", "content": self.config.intervention_message},
            reason=reason,
        ))

    def get_stats(self) -> dict[str, Any]:
        """返回规则引擎统计。"""
        return {
            "running": self._running,
            "short_thought_counts": dict(self._short_thought_counts),
            "custom_rules": [name for name, _, _ in self._custom_rules],
            "config": {
                "max_repeated_short_thoughts": self.config.max_repeated_short_thoughts,
                "short_thought_threshold": self.config.short_thought_threshold,
            },
        }
