"""
Agent层 — ReAct推理循环的实现。

设计参考:
- ReAct paper [https://arxiv.org/abs/2210.03629]: Thought → Action → Observation
- smolagents [https://github.com/huggingface/smolagents] 的 CodeAgent 循环设计

v3.0 新增:
- 流式输出 streaming_callback
- Token预算控制 budget_tokens
- 步级checkpoint checkpoint_enabled
- 温度控制 temperature
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from core.llm import BaseLLM, LLMResponse, Message, ToolCall, Usage
from core.memory import Conversation, StepRecord
from core.tool import Tool, ToolResult, done, think


def _is_permanent_error(exc: Exception) -> bool:
    """判断是否为永久性错误（不应重试）。"""
    # HTTP 4xx 表示请求本身有问题（如参数错误、Token超限）
    if hasattr(exc, "response") and hasattr(exc.response, "status_code"):
        status = exc.response.status_code
        if 400 <= status < 500:
            return True
    # DeepSeek API 的 RuntimeError 包装可能包含状态码文本
    msg = str(exc)
    if "400" in msg or "401" in msg or "402" in msg or "403" in msg:
        return True
    if "Invalid" in msg and "API" in msg:
        return True
    if "token" in msg.lower() and ("limit" in msg.lower() or "exceed" in msg.lower()):
        return True
    return False


@dataclass
class AgentConfig:
    """Agent运行配置。"""
    max_iterations: int = 10
    temperature: float | None = None  # LLM采样温度
    allowed_tools: list[str] | None = None
    stop_on_tool_error: bool = False
    budget_tokens: int = 0  # Token预算，0=无限制
    checkpoint_enabled: bool = False  # 步级checkpoint
    checkpoint_dir: str = os.environ.get("AGENT_CHECKPOINT_DIR", "/tmp/agent_checkpoints")


@dataclass
class AgentResult:
    """Agent执行结果。"""
    success: bool = False
    output: str = ""
    iterations: int = 0
    total_usage: Usage | None = None
    conversation: Conversation | None = None
    stop_reason: str | None = None
    checkpoints: list[str] = field(default_factory=list)  # 保存的checkpoint路径
    artifacts: list[str] = field(default_factory=list)  # 产物文件路径列表


class Agent:
    """
    ReAct Agent — Thought-Action-Observation循环。

    v3.0 特性:
    - streaming: 实时流式输出
    - budget: Token预算控制
    - checkpoint: 步级中间结果保存
    - temperature: 温度控制
    """

    def __init__(
        self,
        llm: BaseLLM,
        tools: list[Tool] | None = None,
        config: AgentConfig | None = None,
        name: str = "agent",
        system_prompt: str | None = None,
    ):
        self.llm = llm
        self.config = config or AgentConfig()
        self.name = name

        # 工具注册
        self._tools: dict[str, Tool] = {}
        self.register_tool(done)
        self.register_tool(think)
        if tools:
            for t in tools:
                self.register_tool(t)

        self.system_prompt = system_prompt or self._default_system_prompt()

        # 产物收集
        self._artifacts: list[str] = []

        # 生命周期钩子
        self.on_step: Callable[[StepRecord], None] | None = None
        self.on_stream: Callable[[str], None] | None = None  # 流式token回调
        self.on_checkpoint: Callable[[dict], None] | None = None  # checkpoint回调
        self.on_complete: Callable[[AgentResult], None] | None = None

    def register_tool(self, tool: Tool) -> None:
        """注册一个工具。"""
        if self.config.allowed_tools and tool.name not in self.config.allowed_tools:
            return
        self._tools[tool.name] = tool

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def get_tool(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def run(
        self,
        task: str,
        conversation: Conversation | None = None,
        stream_callback: Callable[[str], None] | None = None,
    ) -> AgentResult:
        """
        运行Agent处理任务。

        Args:
            task: 用户任务描述
            conversation: 可选的外部Conversation
            stream_callback: 流式回调，每收到一个token调用

        Returns:
            AgentResult: 执行结果
        """
        conv = conversation or Conversation()
        # 避免重复 system prompt（engine 可能已添加）
        if not any(m.role == "system" for m in conv.get_messages()):
            conv.add_system(self.system_prompt)
        conv.add_user(task)

        # 确保checkpoint目录存在
        if self.config.checkpoint_enabled:
            os.makedirs(self.config.checkpoint_dir, exist_ok=True)

        result = AgentResult(conversation=conv)
        final_output = ""
        stop_reason = None
        recent_observations: list[str] = []
        total_usage_so_far = 0
        checkpoint_paths: list[str] = []
        self._artifacts = []  # 每次run重置产物列表

        # 合并流式回调
        effective_stream_cb = stream_callback or self.on_stream

        # 缓存：仅当对话有新消息时才重新 deep copy
        _last_msg_count = -1
        _cached_messages: list[Message] = []

        for i in range(self.config.max_iterations):
            # ── Budget控制 ──────────────────────────────
            if self.config.budget_tokens > 0 and total_usage_so_far >= self.config.budget_tokens:
                stop_reason = f"budget_exceeded({total_usage_so_far}/{self.config.budget_tokens})"
                break

            # 1. 调用LLM（支持streaming和温度，3次重试 + 指数退避）
            current_msg_count = conv.message_count
            if current_msg_count != _last_msg_count:
                messages = conv.get_messages()
                _cached_messages = messages
                _last_msg_count = current_msg_count
            else:
                messages = _cached_messages
            tool_schemas = [t.to_openai_schema() for t in self._tools.values()]

            llm_resp: LLMResponse | None = None
            last_exc: Exception | None = None
            for retry in range(3):
                try:
                    llm_resp = self.llm.chat(
                        messages,
                        tools=tool_schemas,
                        temperature=self.config.temperature,
                        stream_callback=effective_stream_cb,
                    )
                    break
                except Exception as e:
                    last_exc = e
                    # 4xx / 非瞬态错误 → 不重试
                    if _is_permanent_error(e):
                        break
                    if retry < 2:
                        wait = 2 ** retry  # 1s, 2s
                        conv.add_user(
                            f"[retry {retry + 1}/3] LLM call failed ({e}), "
                            f"retrying in {wait}s..."
                        )
                        time.sleep(wait)
                    continue

            if llm_resp is None:
                stop_reason = f"LLM error (3 retries): {last_exc}"
                result = self._build_result(conv, False, final_output, i, stop_reason, checkpoint_paths)
                if self.on_complete:
                    self.on_complete(result)
                return result

            # 累计token
            if llm_resp.usage:
                total_usage_so_far += llm_resp.usage.total_tokens

            # 记录assistant回复
            conv.add_assistant(content=llm_resp.content, tool_calls=llm_resp.tool_calls)

            # 2. 处理tool_calls
            if not llm_resp.tool_calls:
                final_output = llm_resp.content or ""
                stop_reason = "done" if final_output else "no_tool_calls"
                break

            step = StepRecord(thought=llm_resp.content, usage=llm_resp.usage)
            observations: list[str] = []
            should_stop = False

            for tc in llm_resp.tool_calls:
                observation = self._execute_tool_call(tc, conv, step)
                observations.append(observation)
                if tc.function == "done":
                    try:
                        args = json.loads(tc.arguments) if tc.arguments else {}
                        final_output = args.get("result", "")
                    except (json.JSONDecodeError, AttributeError):
                        final_output = observation
                    should_stop = True
                    stop_reason = "done"

            step.observation = "\n".join(observations)
            conv.record_step(step)

            # ── 步级Checkpoint ──────────────────────
            if self.config.checkpoint_enabled:
                ckpt = {
                    "step": i + 1,
                    "thought": step.thought,
                    "action": step.action,
                    "observation": step.observation,
                    "total_tokens": total_usage_so_far,
                    "timestamp": time.time(),
                }
                ckpt_path = os.path.join(
                    self.config.checkpoint_dir,
                    f"ckpt_{conv.session_id}_{i+1:03d}.json"
                )
                try:
                    with open(ckpt_path, "w") as f:
                        json.dump(ckpt, f, ensure_ascii=False)
                    checkpoint_paths.append(ckpt_path)
                except Exception:
                    pass
                if self.on_checkpoint:
                    self.on_checkpoint(ckpt)

            # Stuck检测
            recent_observations.append(step.observation)
            if len(recent_observations) > 3:
                recent_observations.pop(0)
            if len(recent_observations) == 3 and all(o == recent_observations[0] for o in recent_observations):
                stop_reason = "stuck_detected"
                break

            if self.on_step:
                self.on_step(step)

            if should_stop:
                break
        else:
            stop_reason = f"max_iterations_reached({self.config.max_iterations})"

        success = stop_reason == "done"
        result = self._build_result(conv, success, final_output, i + 1, stop_reason, checkpoint_paths)
        if self.on_complete:
            self.on_complete(result)
        return result

    @staticmethod
    def _repair_json(raw: str) -> dict[str, Any]:
        """渐进式修复 LLM 产生的畸形 JSON，力求恢复有效参数。

        策略（按优先级）:
        1. 直接解析
        2. 修复尾逗号
        3. 闭合未终止字符串
        4. 转义字符串内的原始换行和未转义引号
        5. Python bool/None 转 JSON 对应值
        6. 无引号 key 加引号
        """
        if not raw or not raw.strip():
            return {}

        text = raw.strip()

        # 策略 1: 直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 策略 2: 去掉尾逗号
        fixed = re.sub(r",\s*([}\]])", r"\1", text)
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        # 策略 3: 闭合未终止的字符串，并补全未闭合的 {}[]
        if fixed.count('"') % 2 != 0:
            closed = fixed + '"'
            open_braces = closed.count('{') - closed.count('}')
            open_brackets = closed.count('[') - closed.count(']')
            suffix = ''
            if open_braces > 0:
                suffix += '}' * open_braces
            if open_brackets > 0:
                suffix += ']' * open_brackets
            try:
                return json.loads(closed + suffix)
            except json.JSONDecodeError:
                pass

        # 策略 4: 字符串内的未转义换行/引号
        repaired = fixed
        repaired = re.sub(r'(?<!\\)\n', r'\\n', repaired)
        repaired = re.sub(r'(?<!\\)\r', r'\\r', repaired)
        repaired = re.sub(r'(?<!\\)\t', r'\\t', repaired)
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            pass

        # 策略 5: Python bool / None → JSON
        text_lower = text.replace("True", "true").replace("False", "false").replace("None", "null")
        try:
            return json.loads(text_lower)
        except json.JSONDecodeError:
            pass

        # 策略 6: 无引号 key 加引号
        key_quoted = re.sub(r'([{,])\s*([a-zA-Z_]\w*)\s*:', r'\1"\2":', text)
        try:
            return json.loads(key_quoted)
        except json.JSONDecodeError:
            pass

        # 所有策略失败，返回空 dict（调用方可通过日志查看原始文本）
        return {}

    def _execute_tool_call(self, tc: ToolCall, conv: Conversation, step: StepRecord) -> str:
        """执行单个tool call。"""
        tool_name = tc.function
        tool = self._tools.get(tool_name)

        step.action = {"tool_name": tool_name, "arguments": tc.arguments, "tool_call_id": tc.id}

        if not tool:
            error_msg = f"Tool '{tool_name}' not found. Available: {self.list_tools()}"
            conv.add_tool_result(tc.id, tool_name, error_msg)
            return error_msg

        # 解析参数 — 自动修复常见 LLM JSON 错误
        try:
            args = json.loads(tc.arguments) if tc.arguments else {}
        except json.JSONDecodeError as e:
            repaired = self._repair_json(tc.arguments or "")
            if repaired:
                conv.add_system(
                    f"[auto-repair] JSON arguments auto-repaired "
                    f"(reason: {e}). Ensure valid JSON in future calls."
                )
                args = repaired
                # 写回修复后的 JSON，供后续 done 解析等使用
                tc.arguments = json.dumps(args, ensure_ascii=False)
            else:
                error_msg = f"Invalid JSON arguments: {e}"
                conv.add_tool_result(tc.id, tool_name, error_msg)
                return error_msg

        tool_result = tool.execute(**args)
        result_text = tool_result.to_text()
        conv.add_tool_result(tc.id, tool_name, result_text)

        # 收集产物：工具返回 dict 且包含 _artifacts 键
        if isinstance(tool_result.output, dict) and "_artifacts" in tool_result.output:
            self._artifacts.extend(tool_result.output["_artifacts"])

        return result_text

    def _build_result(
        self,
        conv: Conversation,
        success: bool,
        output: str,
        iterations: int,
        stop_reason: str | None,
        checkpoints: list[str],
    ) -> AgentResult:
        return AgentResult(
            success=success,
            output=output,
            iterations=iterations,
            total_usage=conv.total_usage,
            conversation=conv,
            stop_reason=stop_reason,
            checkpoints=checkpoints,
            artifacts=list(dict.fromkeys(self._artifacts)),  # 去重保持顺序
        )

    def _default_system_prompt(self) -> str:
        tool_names = ", ".join(sorted(self._tools.keys())) if self._tools else "none"
        return (
            "You are a helpful AI assistant. You can use tools to solve tasks.\n\n"
            "Available tools: " + tool_names + "\n\n"
            "CRITICAL RULES:\n"
            "1. Think step by step, then act\n"
            "2. Use tools when needed to accomplish the task\n"
            "3. IMMEDIATELY call `done` with final answer after the task is complete\n"
            "   - If you saved a file, call `done` right after saving\n"
            "   - If you wrote code, call `done` after the code is written\n"
            "   - Do NOT keep working after the task is finished\n"
            "4. Use `think` tool if you need to reason through complex steps\n"
            "5. Maximum iterations: " + str(self.config.max_iterations) + "\n"
        )

    def update_system_prompt(self, prompt: str) -> None:
        self.system_prompt = prompt

    def __repr__(self) -> str:
        return f"Agent(name='{self.name}', tools={self.list_tools()}, max_iter={self.config.max_iterations}, budget={self.config.budget_tokens})"
