"""Base tool abstraction — Anthropic tool-use format (input_schema)."""

from __future__ import annotations

import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolResult:
    content: str
    is_error: bool = False

    @classmethod
    def ok(cls, content: str) -> "ToolResult":
        return cls(content=content, is_error=False)

    @classmethod
    def error(cls, message: str) -> "ToolResult":
        return cls(content=message, is_error=True)


class ToolError(Exception):
    """Raised by tool implementations for user-facing errors."""


class BaseTool(ABC):
    """Abstract base for all MacroClaw tools (Anthropic format)."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @property
    @abstractmethod
    def parameters_schema(self) -> dict[str, Any]: ...

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str: ...

    def to_api_dict(self) -> dict[str, Any]:
        """Serialise to Anthropic tool schema (input_schema format)."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters_schema,
        }

    async def safe_execute(self, **kwargs: Any) -> ToolResult:
        try:
            content = await self.execute(**kwargs)
            return ToolResult.ok(content)
        except ToolError as exc:
            return ToolResult.error(f"[{self.name}] {exc}")
        except Exception as exc:  # noqa: BLE001
            tb = traceback.format_exc()
            return ToolResult.error(f"[{self.name}] Unexpected error: {exc}\n{tb}")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r})"
