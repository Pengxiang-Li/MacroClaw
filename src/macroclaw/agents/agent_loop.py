"""AgentLoop — multi-turn agent loop, provider-agnostic."""

from __future__ import annotations

import json
from typing import Any

from macroclaw.agents.model_client import ModelResponse, create_model_client
from macroclaw.agents.system_prompt import PromptMode, build_system_prompt
from macroclaw.agents.tool_registry import ToolRegistry
from macroclaw.config import MacroClawConfig
from macroclaw.logging import get_logger
from macroclaw.memory.manager import MemoryManager
from macroclaw.output.formatter import InvestmentBrief, parse_brief

log = get_logger(__name__, subsystem="agent")

Message = dict[str, Any]


class AgentLoop:
    """MacroClaw's multi-turn agent loop.

    Uses normalised ModelResponse so the loop logic is identical regardless
    of whether the underlying provider is Anthropic, DeerAPI, or OpenAI.
    """

    def __init__(
        self,
        config: MacroClawConfig,
        registry: ToolRegistry,
        memory: MemoryManager,
    ) -> None:
        self._config = config
        self._registry = registry
        self._memory = memory
        self._client = create_model_client(config)
        self._system_prompt = build_system_prompt(
            available_tools=registry.names(),
            mode=PromptMode.FULL,
        )

    async def run(self, user_input: str) -> InvestmentBrief:
        """Run the agent loop and return a parsed InvestmentBrief."""
        messages: list[Message] = [{"role": "user", "content": user_input}]
        tools = self._registry.to_api_list()
        turn = 0

        log.info("Agent loop started", max_turns=self._config.max_turns, query=user_input[:80])

        while turn < self._config.max_turns:
            turn += 1
            log.debug("Agent turn", turn=turn)

            response: ModelResponse = self._client.create_message(
                messages=messages,
                system=self._system_prompt,
                tools=tools or None,
            )

            # Append assistant response as content blocks (Anthropic format)
            messages.append({"role": "assistant", "content": response.content_blocks})

            if response.stop_reason == "end_turn":
                log.info("Agent loop complete", turns=turn, output_len=len(response.text))
                return parse_brief(response.text)

            if response.stop_reason == "tool_use":
                tool_results = await self._dispatch_tool_uses(response)
                messages.append({"role": "user", "content": tool_results})
                continue

            log.warning("Unexpected stop_reason", stop_reason=response.stop_reason)
            return parse_brief(response.text)

        # Max turns — force final answer
        log.warning("Max turns reached, forcing final answer", turns=turn)
        messages.append({
            "role": "user",
            "content": (
                "You have used the maximum number of tool calls. "
                "Based on all data collected, output your final investment brief JSON now."
            ),
        })
        response = self._client.create_message(
            messages=messages,
            system=self._system_prompt,
            tools=None,
        )
        return parse_brief(response.text)

    async def _dispatch_tool_uses(
        self, response: ModelResponse
    ) -> list[dict[str, Any]]:
        """Execute tool calls and return tool_result content blocks."""
        results: list[dict[str, Any]] = []
        for tc in response.tool_calls:
            log.info("Tool call", name=tc.name, id=tc.id)
            result = await self._registry.dispatch(tc.name, tc.input)

            if not result.is_error:
                self._memory.remember(
                    key=f"tool:{tc.name}:{_short_input(tc.input)}",
                    content=result.content,
                    tags=[tc.name],
                )

            results.append({
                "type": "tool_result",
                "tool_use_id": tc.id,
                "content": result.content,
                "is_error": result.is_error,
            })
        return results


def _short_input(inputs: Any) -> str:
    try:
        return json.dumps(inputs, sort_keys=True)[:60]
    except Exception:  # noqa: BLE001
        return str(inputs)[:60]
