"""Model client — unified interface for Anthropic, OpenAI, and DeerAPI.

Provider selection (auto-detected from config.active_provider):
  deerapi   — Anthropic SDK pointed at api.deerapi.com
  anthropic — Anthropic SDK pointed at api.anthropic.com
  openai    — OpenAI SDK pointed at api.openai.com

All providers return a normalised ModelResponse so the agent loop is
provider-agnostic.  Messages are kept in Anthropic format internally;
the OpenAI client converts them on every request.
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx

from macroclaw.config import MacroClawConfig
from macroclaw.logging import get_logger

log = get_logger(__name__, subsystem="model")


# ── Normalised response types ──────────────────────────────────────────────────

@dataclass
class ToolCall:
    """A single tool invocation from the model."""
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ModelResponse:
    """Normalised model response — identical shape regardless of provider."""
    stop_reason: Literal["end_turn", "tool_use"]
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    # Content blocks in Anthropic format, ready to append to message history
    content_blocks: list[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


# ── HTTP helper ────────────────────────────────────────────────────────────────

def _make_http_client() -> httpx.Client:
    """Return an httpx.Client that honours the system HTTPS proxy."""
    proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    if proxy:
        log.debug("Using system proxy", proxy=proxy)
        return httpx.Client(proxy=proxy, timeout=120.0)
    return httpx.Client(timeout=120.0)


# ── Base client ────────────────────────────────────────────────────────────────

class BaseModelClient(ABC):
    """Abstract model client — implemented by AnthropicModelClient and OpenAIModelClient."""

    @abstractmethod
    def create_message(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelResponse: ...


# ── Anthropic client (Anthropic API + DeerAPI) ─────────────────────────────────

class AnthropicModelClient(BaseModelClient):
    """Uses the Anthropic SDK, works for both direct Anthropic API and DeerAPI."""

    def __init__(self, config: MacroClawConfig) -> None:
        import anthropic

        provider = config.active_provider
        if provider == "anthropic":
            api_key = config.anthropic_api_key
            base_url = "https://api.anthropic.com"
            extra_headers: dict[str, str] = {}
        else:  # deerapi
            api_key = config.deerapi_key
            base_url = config.deerapi_base_url
            extra_headers = {"anthropic-beta": "compact-2026-01-12"}

        self._client = anthropic.Anthropic(
            api_key=api_key,
            base_url=base_url,
            http_client=_make_http_client(),
            default_headers=extra_headers,
        )
        self._model = config.model
        self._max_tokens = config.max_tokens
        log.info(
            "Model client initialised",
            model=self._model,
            base_url=base_url,
            provider=provider,
        )

    def create_message(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelResponse:
        import anthropic

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        log.debug("Sending request", model=self._model, turns=len(messages))

        try:
            resp = self._client.messages.create(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise RuntimeError(
                "Authentication failed. Check your API key in .env."
            ) from exc
        except anthropic.RateLimitError as exc:
            raise RuntimeError("Rate limit reached. Wait and retry.") from exc
        except anthropic.APIConnectionError as exc:
            raise RuntimeError(f"Network error: {exc}") from exc

        log.debug(
            "Response received",
            stop_reason=resp.stop_reason,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )

        text = "\n".join(b.text for b in resp.content if b.type == "text")
        tool_calls = [
            ToolCall(id=b.id, name=b.name, input=b.input)
            for b in resp.content
            if b.type == "tool_use"
        ]
        content_blocks: list[dict[str, Any]] = []
        for b in resp.content:
            if b.type == "text":
                content_blocks.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                content_blocks.append(
                    {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
                )

        stop_reason: Literal["end_turn", "tool_use"] = (
            "tool_use" if resp.stop_reason == "tool_use" else "end_turn"
        )
        return ModelResponse(
            stop_reason=stop_reason,
            text=text,
            tool_calls=tool_calls,
            content_blocks=content_blocks,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )


# ── OpenAI client ──────────────────────────────────────────────────────────────

class OpenAIModelClient(BaseModelClient):
    """Uses the OpenAI SDK for the native OpenAI API."""

    def __init__(self, config: MacroClawConfig) -> None:
        import openai

        self._client = openai.OpenAI(
            api_key=config.openai_api_key,
            http_client=_make_http_client(),
        )
        self._model = config.model
        self._max_tokens = config.max_tokens
        log.info("Model client initialised", model=self._model, provider="openai")

    def create_message(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> ModelResponse:
        import openai

        oai_messages = _to_openai_messages(system, messages)
        oai_tools = _to_openai_tools(tools) if tools else None

        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "messages": oai_messages,
        }
        if oai_tools:
            kwargs["tools"] = oai_tools

        log.debug("Sending request", model=self._model, turns=len(oai_messages))

        try:
            resp = self._client.chat.completions.create(**kwargs)
        except openai.AuthenticationError as exc:
            raise RuntimeError(
                "OpenAI authentication failed. Check OPENAI_API_KEY in .env."
            ) from exc
        except openai.RateLimitError as exc:
            raise RuntimeError("OpenAI rate limit reached.") from exc
        except openai.APIConnectionError as exc:
            raise RuntimeError(f"Network error reaching OpenAI: {exc}") from exc

        choice = resp.choices[0]
        msg = choice.message
        finish_reason = choice.finish_reason

        log.debug(
            "Response received",
            finish_reason=finish_reason,
            input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            output_tokens=resp.usage.completion_tokens if resp.usage else 0,
        )

        text = msg.content or ""
        tool_calls: list[ToolCall] = []
        content_blocks: list[dict[str, Any]] = []

        if text:
            content_blocks.append({"type": "text", "text": text})

        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    inputs: dict[str, Any] = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, AttributeError):
                    inputs = {}
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, input=inputs))
                content_blocks.append(
                    {"type": "tool_use", "id": tc.id, "name": tc.function.name, "input": inputs}
                )

        stop_reason_val: Literal["end_turn", "tool_use"] = (
            "tool_use" if finish_reason == "tool_calls" else "end_turn"
        )
        return ModelResponse(
            stop_reason=stop_reason_val,
            text=text,
            tool_calls=tool_calls,
            content_blocks=content_blocks,
            input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            output_tokens=resp.usage.completion_tokens if resp.usage else 0,
        )


# ── Format converters (Anthropic ↔ OpenAI) ────────────────────────────────────

def _to_openai_messages(
    system: str, messages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Convert Anthropic-format message history to OpenAI chat format."""
    oai: list[dict[str, Any]] = [{"role": "system", "content": system}]

    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if isinstance(content, str):
            oai.append({"role": role, "content": content})
            continue

        if role == "assistant":
            text_parts: list[str] = []
            tool_calls_oai: list[dict[str, Any]] = []
            for block in content:
                if block.get("type") == "text":
                    text_parts.append(block["text"])
                elif block.get("type") == "tool_use":
                    tool_calls_oai.append({
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block["input"]),
                        },
                    })
            oai_msg: dict[str, Any] = {"role": "assistant"}
            if text_parts:
                oai_msg["content"] = "\n".join(text_parts)
            else:
                oai_msg["content"] = None
            if tool_calls_oai:
                oai_msg["tool_calls"] = tool_calls_oai
            oai.append(oai_msg)

        elif role == "user":
            has_tool_result = any(
                isinstance(b, dict) and b.get("type") == "tool_result"
                for b in content
            )
            if has_tool_result:
                # Each tool_result → separate "tool" role message
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        result_content = block.get("content", "")
                        if isinstance(result_content, list):
                            result_content = "\n".join(
                                b.get("text", "")
                                for b in result_content
                                if isinstance(b, dict)
                            )
                        oai.append({
                            "role": "tool",
                            "tool_call_id": block["tool_use_id"],
                            "content": result_content,
                        })
            else:
                text = "\n".join(
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
                if text:
                    oai.append({"role": "user", "content": text})

    return oai


def _to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Anthropic-format tool definitions to OpenAI function tool format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("input_schema", {}),
            },
        }
        for t in tools
    ]


# ── Factory ────────────────────────────────────────────────────────────────────

def create_model_client(config: MacroClawConfig) -> BaseModelClient:
    """Instantiate the correct model client based on config.active_provider."""
    provider = config.active_provider
    if provider == "openai":
        return OpenAIModelClient(config)
    return AnthropicModelClient(config)  # "anthropic" or "deerapi"


# Backward-compatibility alias
ModelClient = AnthropicModelClient
