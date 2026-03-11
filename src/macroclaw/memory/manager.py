"""MemoryManager — lightweight in-session context memory.

Mirrors OpenClaw's MemoryIndexManager in spirit but uses a simpler
in-process store (no vector DB required for v1). Keeps a rolling window
of key observations from the current session so the agent can recall
prior fetches without re-calling tools.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from macroclaw.logging import get_logger

log = get_logger(__name__, subsystem="memory")

MAX_ENTRIES = 50          # rolling window size
MAX_CONTENT_CHARS = 2000  # truncate long tool outputs before storing


@dataclass
class MemoryEntry:
    """A single observation stored in the session memory."""

    key: str
    content: str
    tags: list[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "content": self.content,
            "tags": self.tags,
            "created_at": self.created_at,
        }


class MemoryManager:
    """Session-scoped memory with optional JSON persistence.

    The agent loop calls remember() after each successful tool result and
    recall() to check for cached observations before re-fetching data.
    """

    def __init__(self, enabled: bool = True, persist_path: str | None = None) -> None:
        self._enabled = enabled
        self._store: deque[MemoryEntry] = deque(maxlen=MAX_ENTRIES)
        self._persist_path: Path | None = (
            Path(persist_path).expanduser() if persist_path else None
        )
        if self._persist_path:
            self._load_from_disk()

    # ── Write ──────────────────────────────────────────────────────────────

    def remember(self, key: str, content: str, tags: list[str] | None = None) -> None:
        """Store an observation under *key*.

        If an entry with the same key already exists, it is replaced.
        Long content is truncated to MAX_CONTENT_CHARS.
        """
        if not self._enabled:
            return

        content = content[:MAX_CONTENT_CHARS]
        # Replace existing entry with the same key
        self._store = deque(
            (e for e in self._store if e.key != key),
            maxlen=MAX_ENTRIES,
        )
        entry = MemoryEntry(key=key, content=content, tags=tags or [])
        self._store.append(entry)
        log.debug("Stored memory entry", key=key, tags=tags or [])

    # ── Read ───────────────────────────────────────────────────────────────

    def recall(self, key: str) -> MemoryEntry | None:
        """Retrieve the entry for *key*, or None if not present."""
        for entry in reversed(self._store):
            if entry.key == key:
                return entry
        return None

    def search(self, query: str) -> list[MemoryEntry]:
        """Simple keyword search across all stored entries."""
        q = query.lower()
        return [
            e for e in self._store
            if q in e.key.lower() or q in e.content.lower()
            or any(q in tag.lower() for tag in e.tags)
        ]

    def all_entries(self) -> list[MemoryEntry]:
        return list(self._store)

    def to_context_string(self) -> str:
        """Render memory as a compact string for injection into the prompt."""
        if not self._store:
            return "(no prior session memory)"
        lines = []
        for e in self._store:
            lines.append(f"[{e.created_at}] {e.key}: {e.content[:300]}")
        return "\n".join(lines)

    # ── Persistence ────────────────────────────────────────────────────────

    def save_to_disk(self) -> None:
        """Persist current memory to JSON (called at session end)."""
        if not self._persist_path:
            return
        self._persist_path.parent.mkdir(parents=True, exist_ok=True)
        data = [e.to_dict() for e in self._store]
        self._persist_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        log.debug("Memory persisted", path=str(self._persist_path), entries=len(data))

    def _load_from_disk(self) -> None:
        if not self._persist_path or not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            for item in data[-MAX_ENTRIES:]:
                self._store.append(
                    MemoryEntry(
                        key=item["key"],
                        content=item["content"],
                        tags=item.get("tags", []),
                        created_at=item.get("created_at", ""),
                    )
                )
            log.info("Memory loaded from disk", entries=len(self._store))
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to load memory from disk", error=str(exc))

    def clear(self) -> None:
        self._store.clear()
