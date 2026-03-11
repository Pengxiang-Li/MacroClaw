"""GeopoliticalNewsFetcher — Phase 2, Data Ingestion Module 1.

Fetches breaking geopolitical news and analysis from:
  1. GDELT Project API v2 (free, no key required) — primary source
  2. NewsAPI.org (key optional) — supplementary source

Both adapters implement the same interface so new sources can be plugged in
without touching the tool's execute() logic (open/closed principle).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx

from macroclaw.logging import get_logger
from macroclaw.tools.base import BaseTool, ToolError

log = get_logger(__name__, subsystem="geo-news")


# ── Data models ────────────────────────────────────────────────────────────────

class NewsArticle:
    """Lightweight article container — avoids heavy ORM / Pydantic overhead."""

    __slots__ = ("title", "url", "source", "published_at", "summary", "tone")

    def __init__(
        self,
        title: str,
        url: str,
        source: str,
        published_at: str,
        summary: str = "",
        tone: float | None = None,
    ) -> None:
        self.title = title
        self.url = url
        self.source = source
        self.published_at = published_at
        self.summary = summary
        self.tone = tone  # GDELT tone: negative = conflict/fear, positive = optimism

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "published_at": self.published_at,
            "summary": self.summary,
            **({"tone": self.tone} if self.tone is not None else {}),
        }


# ── Adapters ───────────────────────────────────────────────────────────────────

class _GdeltAdapter:
    """GDELT Project DocAPI v2 adapter.

    Requires no API key. Free tier returns up to 250 articles per request.
    Docs: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
    """

    BASE_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
    DEFAULT_TIMEOUT = 15.0

    async def fetch(
        self,
        query: str,
        max_results: int = 10,
        time_span: str = "48h",
    ) -> list[NewsArticle]:
        """Fetch articles matching *query* from GDELT with retry on 429."""
        import asyncio

        params = {
            "query": query,
            "mode": "ArtList",
            "maxrecords": str(min(max_results, 250)),
            "timespan": time_span,
            "sort": "DateDesc",
            "format": "json",
        }
        url = f"{self.BASE_URL}?{'&'.join(f'{k}={quote_plus(str(v))}' for k, v in params.items())}"

        log.debug("GDELT request", url=url)

        async with httpx.AsyncClient(timeout=self.DEFAULT_TIMEOUT) as client:
            for attempt in range(3):
                try:
                    resp = await client.get(url)
                    if resp.status_code == 429:
                        wait = 2 ** attempt
                        log.warning("GDELT rate limited, retrying", attempt=attempt + 1, wait=wait)
                        await asyncio.sleep(wait)
                        continue
                    resp.raise_for_status()
                    break
                except httpx.TimeoutException as exc:
                    raise ToolError(f"GDELT request timed out: {exc}") from exc
                except httpx.HTTPStatusError as exc:
                    raise ToolError(
                        f"GDELT returned HTTP {exc.response.status_code}"
                    ) from exc
                except httpx.RequestError as exc:
                    raise ToolError(f"GDELT network error: {exc}") from exc
            else:
                raise ToolError("GDELT rate limit persists after 3 retries.")

        data = resp.json()
        raw_articles = data.get("articles", [])
        articles: list[NewsArticle] = []

        for item in raw_articles[:max_results]:
            articles.append(
                NewsArticle(
                    title=item.get("title", "(no title)"),
                    url=item.get("url", ""),
                    source=item.get("domain", "unknown"),
                    published_at=item.get("seendate", ""),
                    summary="",
                    tone=item.get("tone"),
                )
            )

        log.info("GDELT fetch complete", count=len(articles), query=query)
        return articles


class _NewsApiAdapter:
    """NewsAPI.org adapter.

    Requires a free API key (100 req/day on free tier).
    Docs: https://newsapi.org/docs/endpoints/everything
    """

    BASE_URL = "https://newsapi.org/v2/everything"
    DEFAULT_TIMEOUT = 15.0

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def fetch(
        self,
        query: str,
        max_results: int = 10,
        language: str = "en",
    ) -> list[NewsArticle]:
        params = {
            "q": query,
            "apiKey": self._api_key,
            "language": language,
            "sortBy": "publishedAt",
            "pageSize": str(min(max_results, 100)),
        }

        log.debug("NewsAPI request", query=query)

        async with httpx.AsyncClient(timeout=self.DEFAULT_TIMEOUT) as client:
            try:
                resp = await client.get(self.BASE_URL, params=params)
                resp.raise_for_status()
            except httpx.TimeoutException as exc:
                raise ToolError(f"NewsAPI request timed out: {exc}") from exc
            except httpx.HTTPStatusError as exc:
                body = exc.response.text[:200]
                raise ToolError(
                    f"NewsAPI returned HTTP {exc.response.status_code}: {body}"
                ) from exc
            except httpx.RequestError as exc:
                raise ToolError(f"NewsAPI network error: {exc}") from exc

        data = resp.json()
        if data.get("status") != "ok":
            raise ToolError(f"NewsAPI error: {data.get('message', 'unknown')}")

        articles: list[NewsArticle] = []
        for item in data.get("articles", [])[:max_results]:
            articles.append(
                NewsArticle(
                    title=item.get("title", "(no title)"),
                    url=item.get("url", ""),
                    source=item.get("source", {}).get("name", "unknown"),
                    published_at=item.get("publishedAt", ""),
                    summary=item.get("description") or "",
                )
            )

        log.info("NewsAPI fetch complete", count=len(articles), query=query)
        return articles


# ── Tool ───────────────────────────────────────────────────────────────────────

class GeopoliticalNewsFetcher(BaseTool):
    """Fetch breaking geopolitical news from GDELT and/or NewsAPI.

    Primary source: GDELT (no key required).
    Supplementary source: NewsAPI (key required; falls back gracefully).

    Returns a JSON array of article objects suitable for LLM consumption.
    """

    def __init__(self, news_api_key: str = "") -> None:
        self._gdelt = _GdeltAdapter()
        self._newsapi = _NewsApiAdapter(news_api_key) if news_api_key else None

    # ── BaseTool contract ──────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "fetch_geopolitical_news"

    @property
    def description(self) -> str:
        return (
            "Fetch recent geopolitical news articles related to a query. "
            "Use this to monitor conflicts, international relations, sanctions, "
            "trade disputes, and other macro-political events that affect commodity markets. "
            "Returns a list of articles with titles, sources, publication times, and "
            "sentiment tone where available."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Search query for geopolitical events, e.g. "
                        "'Middle East oil conflict', 'Russia Ukraine sanctions', "
                        "'OPEC production cut'"
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of articles to return (default 10, max 20).",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 20,
                },
                "time_span": {
                    "type": "string",
                    "description": (
                        "How far back to search. GDELT accepts values like '24h', '48h', '7d'. "
                        "Default: '48h'."
                    ),
                    "default": "48h",
                },
                "use_newsapi": {
                    "type": "boolean",
                    "description": (
                        "Also query NewsAPI.org (requires NEWS_API_KEY). Default: true."
                    ),
                    "default": True,
                },
            },
            "required": ["query"],
        }

    async def execute(
        self,
        query: str,
        max_results: int = 10,
        time_span: str = "48h",
        use_newsapi: bool = True,
        **_: Any,
    ) -> str:
        """Fetch articles and return a formatted JSON string."""
        max_results = max(1, min(max_results, 20))
        articles: list[NewsArticle] = []

        # 1. GDELT (primary, always attempted)
        try:
            gdelt_articles = await self._gdelt.fetch(
                query=query,
                max_results=max_results,
                time_span=time_span,
            )
            articles.extend(gdelt_articles)
        except ToolError as exc:
            log.warning("GDELT fetch failed, continuing", error=str(exc))

        # 2. NewsAPI (supplementary, only if key configured and requested)
        if use_newsapi and self._newsapi:
            remaining = max(0, max_results - len(articles))
            if remaining > 0:
                try:
                    newsapi_articles = await self._newsapi.fetch(
                        query=query,
                        max_results=remaining,
                    )
                    articles.extend(newsapi_articles)
                except ToolError as exc:
                    log.warning("NewsAPI fetch failed, continuing", error=str(exc))

        if not articles:
            raise ToolError(
                f"No articles found for query '{query}'. "
                "Try a broader query or a longer time_span."
            )

        # Deduplicate by URL
        seen: set[str] = set()
        unique: list[NewsArticle] = []
        for art in articles:
            if art.url not in seen:
                seen.add(art.url)
                unique.append(art)

        result = {
            "query": query,
            "time_span": time_span,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "total_articles": len(unique),
            "articles": [a.to_dict() for a in unique[:max_results]],
        }
        return json.dumps(result, indent=2, ensure_ascii=False)
