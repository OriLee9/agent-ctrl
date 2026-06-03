"""
LLM抽象层 — 统一模型调用的接口。

设计参考:
- smolagents [https://github.com/huggingface/smolagents] 的TransformersModel/OpenAIServerModel
- MiniCode-Agent [https://github.com/xu-kai-quan/MiniCode-Agent] 的双后端切换思路

原则:
- 纯标准库+requests，不依赖任何框架
- 接口极简: chat(messages, tools=None) -> (content, tool_calls, usage)
- 预留多Provider扩展点
"""
from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

# Re-export Callable for downstream use
__all__ = ["BaseLLM", "DeepSeekLLM", "OpenAILLM", "LLMResponse", "Message", "ToolCall", "Usage", "llm_from_env", "resolve_deepseek_model"]

import requests


@dataclass
class Message:
    """对话消息 — 兼容OpenAI message格式。"""
    role: str  # "system" | "user" | "assistant" | "tool"
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None  # tool name for tool role

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"role": self.role}
        if self.content is not None:
            d["content"] = self.content
        if self.tool_calls:
            d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        if self.tool_call_id is not None:
            d["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            d["name"] = self.name
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Message":
        tool_calls = None
        if "tool_calls" in d:
            tool_calls = [ToolCall.from_dict(tc) for tc in d["tool_calls"]]
        return cls(
            role=d["role"],
            content=d.get("content"),
            tool_calls=tool_calls,
            tool_call_id=d.get("tool_call_id"),
            name=d.get("name"),
        )


@dataclass
class ToolCall:
    """模型请求调用的工具。"""
    id: str
    function: str  # 函数名
    arguments: str  # JSON字符串参数

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.function,
                "arguments": self.arguments,
            },
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ToolCall":
        func = d["function"]
        return cls(
            id=d["id"],
            function=func["name"],
            arguments=func["arguments"],
        )


@dataclass
class Usage:
    """Token使用统计。"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """LLM调用的标准化响应。"""
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage | None = None
    raw: dict | None = None  # 保留原始响应用于调试


class BaseLLM(ABC):
    """LLM抽象基类。"""

    @abstractmethod
    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> LLMResponse:
        """发送对话请求，返回标准化响应。"""

    @abstractmethod
    def model_id(self) -> str:
        """返回模型标识。"""


class DeepSeekLLM(BaseLLM):
    """
    DeepSeek API 实现。

    参考 DeepSeek API 文档 [https://api-docs.deepseek.com/]:
    - 兼容 OpenAI API 格式
    - 支持 /chat/completions
    - 支持 function calling (tools)
    """

    def __init__(
        self,
        model: str = "deepseek-chat",
        api_key: str | None = None,
        base_url: str = "https://api.deepseek.com/v1",
        timeout: int = 120,
    ):
        self.model = model
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError("DeepSeek API key required: pass api_key or set DEEPSEEK_API_KEY env var")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def model_id(self) -> str:
        return f"deepseek:{self.model}"

    def chat(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        temperature: float | None = None,
        stream_callback: Callable[[str], None] | None = None,
    ) -> LLMResponse:
        """
        调用LLM，支持温度控制和流式输出。

        Args:
            messages: 对话消息列表
            tools: 可用工具Schema
            temperature: 采样温度(0-2)，None使用模型默认
            stream_callback: 流式回调函数，每收到一个token调用一次
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
        }
        if tools:
            payload["tools"] = tools
        if temperature is not None:
            payload["temperature"] = temperature

        # 流式模式
        if stream_callback is not None:
            payload["stream"] = True
            return self._chat_stream(payload, stream_callback)

        # 非流式模式
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            # 诊断：输出请求体摘要和响应内容
            body_preview = json.dumps(payload, ensure_ascii=False)[:500]
            resp_body = ""
            if hasattr(e, "response") and e.response is not None:
                resp_body = (e.response.text or "")[:500]
            raise RuntimeError(
                f"DeepSeek API request failed: {e}\n"
                f"  Request body (first 500 chars): {body_preview}\n"
                f"  Response body: {resp_body}"
            ) from e

        data = resp.json()
        choice = data["choices"][0]
        message_data = choice["message"]

        tool_calls = []
        if "tool_calls" in message_data and message_data["tool_calls"]:
            tool_calls = [ToolCall.from_dict(tc) for tc in message_data["tool_calls"]]

        usage = None
        if "usage" in data:
            usage = Usage(
                prompt_tokens=data["usage"].get("prompt_tokens", 0),
                completion_tokens=data["usage"].get("completion_tokens", 0),
                total_tokens=data["usage"].get("total_tokens", 0),
            )

        # 兜底：某些 API/代理在非流式模式下不返回 usage，按内容长度估算
        if usage is None:
            content_str = message_data.get("content", "") or ""
            est_tokens = max(len(content_str) // 4, 1)
            usage = Usage(completion_tokens=est_tokens, total_tokens=est_tokens)

        return LLMResponse(
            content=message_data.get("content"),
            tool_calls=tool_calls,
            usage=usage,
            raw=data,
        )

    def _chat_stream(
        self,
        payload: dict[str, Any],
        callback: Callable[[str], None],
    ) -> LLMResponse:
        """流式调用实现(SSE)。"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        content_parts: list[str] = []
        tool_calls_raw: dict[str, dict] = {}
        usage: Usage | None = None

        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
                stream=True,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            body_preview = json.dumps(payload, ensure_ascii=False)[:500]
            resp_body = ""
            if hasattr(e, "response") and e.response is not None:
                resp_body = (e.response.text or "")[:500]
            raise RuntimeError(
                f"DeepSeek API stream failed: {e}\n"
                f"  Request body (first 500 chars): {body_preview}\n"
                f"  Response body: {resp_body}"
            ) from e

        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            data_str = line[6:]  # strip "data: "
            if data_str == "[DONE]":
                break

            try:
                chunk = json.loads(data_str)
            except json.JSONDecodeError:
                continue

            delta = chunk.get("choices", [{}])[0].get("delta", {})

            # 流式content
            if "content" in delta and delta["content"]:
                token = delta["content"]
                content_parts.append(token)
                callback(token)

            # 流式tool_calls
            if "tool_calls" in delta and delta["tool_calls"]:
                for tc in delta["tool_calls"]:
                    idx = str(tc.get("index", 0))
                    if idx not in tool_calls_raw:
                        tool_calls_raw[idx] = {"id": "", "function": {"name": "", "arguments": ""}}
                    if "id" in tc:
                        tool_calls_raw[idx]["id"] = tc["id"]
                    if "function" in tc:
                        func = tc["function"]
                        if "name" in func:
                            tool_calls_raw[idx]["function"]["name"] += func["name"]
                        if "arguments" in func:
                            tool_calls_raw[idx]["function"]["arguments"] += func["arguments"]

            # usage只在最后一条
            if "usage" in chunk:
                u = chunk["usage"]
                usage = Usage(
                    prompt_tokens=u.get("prompt_tokens", 0),
                    completion_tokens=u.get("completion_tokens", 0),
                    total_tokens=u.get("total_tokens", 0),
                )

        # 如果没有收到usage，估算
        if usage is None:
            total_chars = sum(len(p) for p in content_parts)
            # 粗略估算: 1 token ≈ 4 chars
            est_tokens = total_chars // 4
            usage = Usage(completion_tokens=est_tokens, total_tokens=est_tokens)

        content = "".join(content_parts)

        # 解析tool_calls
        tool_calls = []
        for tc_data in tool_calls_raw.values():
            if tc_data["id"] and tc_data["function"]["name"]:
                tool_calls.append(ToolCall(
                    id=tc_data["id"],
                    function=tc_data["function"]["name"],
                    arguments=tc_data["function"]["arguments"],
                ))

        return LLMResponse(
            content=content or None,
            tool_calls=tool_calls,
            usage=usage,
            raw={"streamed": True, "chunks": len(content_parts)},
        )


class OpenAILLM(BaseLLM):
    """OpenAI兼容API的通用实现（可用于其他兼容OpenAI格式的Provider）。"""

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        base_url: str = "https://api.openai.com/v1",
        timeout: int = 120,
    ):
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("OpenAI API key required: pass api_key or set OPENAI_API_KEY env var")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def model_id(self) -> str:
        return f"openai:{self.model}"

    def chat(self, messages: list[Message], tools: list[dict] | None = None) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_dict() for m in messages],
        }
        if tools:
            payload["tools"] = tools

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"OpenAI API request failed: {e}") from e

        data = resp.json()
        choice = data["choices"][0]
        message_data = choice["message"]

        tool_calls = []
        if "tool_calls" in message_data and message_data["tool_calls"]:
            tool_calls = [ToolCall.from_dict(tc) for tc in message_data["tool_calls"]]

        usage = None
        if "usage" in data:
            usage = Usage(
                prompt_tokens=data["usage"].get("prompt_tokens", 0),
                completion_tokens=data["usage"].get("completion_tokens", 0),
                total_tokens=data["usage"].get("total_tokens", 0),
            )

        return LLMResponse(
            content=message_data.get("content"),
            tool_calls=tool_calls,
            usage=usage,
            raw=data,
        )


def resolve_deepseek_model(api_type: str | None = None, fallback: str = "deepseek-v4-pro") -> str:
    """将 DEEPSEEK_API_TYPE 映射为实际模型 ID。

    支持类型:
        v4-pro   → deepseek-v4-pro   (默认)
        v4-flash → deepseek-v4-flash

    Args:
        api_type: 配置类型别名，默认读取 DEEPSEEK_API_TYPE 环境变量
        fallback: 无法解析时的回退模型 ID

    Returns:
        实际模型 ID 字符串
    """
    if api_type is None:
        api_type = os.getenv("DEEPSEEK_API_TYPE", "")

    mapping = {
        "v4-pro": "deepseek-v4-pro",
        "v4-flash": "deepseek-v4-flash",
    }

    # 如果直接设置了 DEEPSEEK_MODEL，优先使用（最高优先级）
    explicit_model = os.getenv("DEEPSEEK_MODEL")
    if explicit_model:
        return explicit_model

    # 根据 API_TYPE 映射
    normalized = api_type.strip().lower() if api_type else ""
    if normalized in mapping:
        return mapping[normalized]

    return fallback


def llm_from_env() -> BaseLLM:
    """
    从环境变量自动创建LLM实例。
    优先使用DEEPSEEK_API_KEY，其次OPENAI_API_KEY。
    """
    if os.getenv("DEEPSEEK_API_KEY"):
        return DeepSeekLLM(
            model=resolve_deepseek_model(),
            api_key=os.getenv("DEEPSEEK_API_KEY"),
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
        )
    if os.getenv("OPENAI_API_KEY"):
        return OpenAILLM(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            api_key=os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        )
    raise ValueError("No API key found: set DEEPSEEK_API_KEY or OPENAI_API_KEY")
