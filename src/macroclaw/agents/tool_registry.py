"""ToolRegistry — mirrors OpenClaw's pi-tools registration + policy pipeline.

Manages tool registration, schema export for the Anthropic API,
and dispatches tool_use calls back to the correct BaseTool.execute().
"""

from __future__ import annotations

from typing import Any

from macroclaw.logging import get_logger
from macroclaw.tools.base import BaseTool, ToolResult

log = get_logger(__name__, subsystem="tool-registry")


class ToolRegistry:
    """Central registry for all MacroClaw tools.

    Usage::

        registry = ToolRegistry()
        registry.register(GeopoliticalNewsFetcher(news_api_key=...))
        registry.register(CommodityDataFetcher(alpha_vantage_key=...))

        # Get list of dicts for the Anthropic API 'tools' parameter
        api_tools = registry.to_api_list()

        # Dispatch a tool_use block from the LLM response
        result = await registry.dispatch("fetch_geopolitical_news", {"query": "OPEC"})
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool, raising if the name is already taken."""
        if tool.name in self._tools:
            raise ValueError(
                f"Tool '{tool.name}' is already registered. "
                "Use a unique name or unregister the existing tool first."
            )
        self._tools[tool.name] = tool
        log.debug("Tool registered", name=tool.name)

    def unregister(self, name: str) -> None:
        """Remove a tool by name (idempotent)."""
        self._tools.pop(name, None)

    def names(self) -> list[str]:
        """Return the names of all registered tools."""
        return list(self._tools.keys())

    def to_api_list(self) -> list[dict[str, Any]]:
        """Serialise all tools to the Anthropic messages API format.

        Returns a list compatible with the ``tools`` parameter of
        ``anthropic.Anthropic().messages.create()``.
        """
        return [tool.to_api_dict() for tool in self._tools.values()]

    async def dispatch(self, name: str, inputs: dict[str, Any]) -> ToolResult:
        """Dispatch a tool_use call from the LLM to the appropriate tool.

        Mirrors OpenClaw's executeToolCall() with the same safe-execution
        contract: always returns a ToolResult, never raises.

        Args:
            name: Tool name from the LLM's tool_use block.
            inputs: Parsed JSON inputs from the LLM's tool_use block.
        """
        tool = self._tools.get(name)
        if tool is None:
            available = ", ".join(self.names()) or "(none)"
            return ToolResult.error(
                f"Unknown tool '{name}'. Available tools: {available}"
            )

        log.info("Dispatching tool", name=name, inputs=list(inputs.keys()))
        result = await tool.safe_execute(**inputs)

        if result.is_error:
            log.warning("Tool returned error", name=name, error=result.content[:200])
        else:
            log.debug("Tool succeeded", name=name, content_len=len(result.content))

        return result

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"ToolRegistry(tools={self.names()})"
