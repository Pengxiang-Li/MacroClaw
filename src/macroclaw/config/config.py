"""MacroClaw configuration — Pydantic Settings, all values from .env.

Supported LLM providers (in auto-detection priority order):
  1. deerapi   — DeerAPI gateway (DEERAPI_KEY)
  2. anthropic — Anthropic API directly (ANTHROPIC_API_KEY)
  3. openai    — OpenAI API directly (OPENAI_API_KEY)

Set LLM_PROVIDER explicitly to override auto-detection.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Provider = Literal["deerapi", "anthropic", "openai"]

# Default models per provider
_DEFAULT_MODELS: dict[str, str] = {
    "deerapi": "claude-opus-4-6",
    "anthropic": "claude-opus-4-6",
    "openai": "gpt-4o",
}


class MacroClawConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM provider selection ────────────────────────────────────────────────
    llm_provider: str = Field(default="", alias="LLM_PROVIDER")

    # ── DeerAPI ───────────────────────────────────────────────────────────────
    deerapi_key: str = Field(default="", alias="DEERAPI_KEY")
    deerapi_base_url: str = Field(
        default="https://api.deerapi.com", alias="DEERAPI_BASE_URL"
    )

    # ── Anthropic API ─────────────────────────────────────────────────────────
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")

    # ── OpenAI API ────────────────────────────────────────────────────────────
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")

    # ── Model settings ────────────────────────────────────────────────────────
    macroclaw_model: str = Field(default="", alias="MACROCLAW_MODEL")
    macroclaw_max_tokens: int = Field(default=8192)
    macroclaw_max_turns: int = Field(default=10)

    # ── News API ──────────────────────────────────────────────────────────────
    news_api_key: str = Field(default="", alias="NEWS_API_KEY")

    # ── Commodity / Financial APIs ────────────────────────────────────────────
    alpha_vantage_api_key: str = Field(default="", alias="ALPHA_VANTAGE_API_KEY")
    fred_api_key: str = Field(default="", alias="FRED_API_KEY")

    # ── Memory ────────────────────────────────────────────────────────────────
    macroclaw_memory_enabled: bool = Field(default=True)
    macroclaw_memory_path: str = Field(default="~/.macroclaw/memory")

    # ── Logging ───────────────────────────────────────────────────────────────
    macroclaw_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    macroclaw_log_file: str = Field(default="~/.macroclaw/macroclaw.log")

    @field_validator("macroclaw_memory_path", "macroclaw_log_file", mode="before")
    @classmethod
    def expand_path(cls, v: str) -> str:
        return str(Path(v).expanduser())

    # ── Derived properties ────────────────────────────────────────────────────

    @property
    def active_provider(self) -> Provider:
        """Resolve which LLM provider to use."""
        explicit = self.llm_provider.lower().strip()
        if explicit in ("deerapi", "anthropic", "openai"):
            return explicit  # type: ignore[return-value]
        # Auto-detect by key presence
        if self.deerapi_key:
            return "deerapi"
        if self.anthropic_api_key:
            return "anthropic"
        if self.openai_api_key:
            return "openai"
        return "deerapi"  # will fail validation later with a helpful message

    @property
    def model(self) -> str:
        if self.macroclaw_model:
            return self.macroclaw_model
        return _DEFAULT_MODELS.get(self.active_provider, "claude-opus-4-6")

    @property
    def max_tokens(self) -> int:
        return self.macroclaw_max_tokens

    @property
    def max_turns(self) -> int:
        return self.macroclaw_max_turns

    @property
    def log_level(self) -> str:
        return self.macroclaw_log_level

    @property
    def log_file(self) -> str:
        return self.macroclaw_log_file

    @property
    def memory_enabled(self) -> bool:
        return self.macroclaw_memory_enabled

    @property
    def memory_path(self) -> str:
        return self.macroclaw_memory_path

    def has_news_api(self) -> bool:
        return bool(self.news_api_key)

    def has_alpha_vantage(self) -> bool:
        return bool(self.alpha_vantage_api_key)

    def validate_required(self) -> list[str]:
        """Return list of missing required env var names."""
        provider = self.active_provider
        if provider == "deerapi" and not self.deerapi_key:
            return ["DEERAPI_KEY"]
        if provider == "anthropic" and not self.anthropic_api_key:
            return ["ANTHROPIC_API_KEY"]
        if provider == "openai" and not self.openai_api_key:
            return ["OPENAI_API_KEY"]
        # No keys at all
        if not self.deerapi_key and not self.anthropic_api_key and not self.openai_api_key:
            return ["DEERAPI_KEY or ANTHROPIC_API_KEY or OPENAI_API_KEY"]
        return []


@lru_cache(maxsize=1)
def load_config() -> MacroClawConfig:
    env_path = os.environ.get("MACROCLAW_ENV_FILE", ".env")
    return MacroClawConfig(_env_file=env_path)  # type: ignore[call-arg]
