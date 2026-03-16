"""CommodityDataFetcher — Phase 2, Data Ingestion Module 2.

Fetches real-time and historical price data for:
  - Crude Oil: WTI (CL=F) and Brent (BZ=F) futures
  - Gold: XAU spot (GC=F futures, GLD ETF, XAUUSD=X)

Data sources (in priority order):
  1. yfinance — free, no key, Yahoo Finance data
  2. Alpha Vantage — structured API, key optional (25 req/day free)

Designed to be modular: new assets (currencies, indices, etc.) can be added
by registering new ticker aliases in TICKER_MAP without touching execute().
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx

from macroclaw.logging import get_logger
from macroclaw.tools.base import BaseTool, ToolError

log = get_logger(__name__, subsystem="commodity")


# ── Ticker registry ────────────────────────────────────────────────────────────
# Maps user-friendly asset names to yfinance ticker symbols.
# Add new assets here to extend MacroClaw to cover additional commodities/FX.

TICKER_MAP: dict[str, str] = {
    # Crude Oil
    "wti": "CL=F",
    "wti_crude": "CL=F",
    "crude_oil": "CL=F",
    "cl": "CL=F",
    "brent": "BZ=F",
    "brent_crude": "BZ=F",
    "bz": "BZ=F",
    # Gold
    "gold": "GC=F",
    "xau": "GC=F",
    "gc": "GC=F",
    "xauusd": "XAUUSD=X",
    "gld": "GLD",
    # Silver (for future expansion)
    "silver": "SI=F",
    "xag": "SI=F",
    # Natural Gas (for future expansion)
    "natgas": "NG=F",
    "natural_gas": "NG=F",
    # Currencies & Forex
    "dxy": "DX=F",
    "usd": "DX=F",
    "jpy": "JPY=X",
    "usdjpy": "JPY=X",
    "chf": "CHF=X",
    "usdchf": "CHF=X",
}

# Human-readable labels for output
ASSET_LABELS: dict[str, str] = {
    "CL=F": "WTI Crude Oil (USD/bbl)",
    "BZ=F": "Brent Crude Oil (USD/bbl)",
    "GC=F": "Gold Futures (USD/troy oz)",
    "XAUUSD=X": "Gold Spot XAU/USD",
    "GLD": "SPDR Gold ETF (USD)",
    "SI=F": "Silver Futures (USD/troy oz)",
    "NG=F": "Natural Gas (USD/MMBtu)",
    "DX=F": "US Dollar Index (DXY)",
    "JPY=X": "USD/JPY (Japanese Yen)",
    "CHF=X": "USD/CHF (Swiss Franc)",
}

VALID_PERIODS = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y"}
VALID_INTERVALS = {"1m", "5m", "15m", "30m", "60m", "1h", "1d", "1wk", "1mo"}


# ── yfinance adapter ──────────────────────────────────────────────────────────

class _YFinanceAdapter:
    """yfinance wrapper — lazy-imports yfinance to avoid import-time side effects."""

    async def get_current_price(self, ticker: str) -> dict[str, Any]:
        """Return the latest OHLCV snapshot for *ticker*."""
        try:
            import yfinance as yf  # lazy import
        except ImportError as exc:
            raise ToolError(
                "yfinance is not installed. Run: pip install yfinance"
            ) from exc

        try:
            t = yf.Ticker(ticker)
            info = t.fast_info  # lightweight dict, avoids full .info call
            hist = t.history(period="2d", interval="1d", auto_adjust=True)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"yfinance error for {ticker}: {exc}") from exc

        if hist.empty:
            raise ToolError(
                f"No price data returned for ticker '{ticker}'. "
                "It may be delisted or the market is closed."
            )

        latest = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) >= 2 else None

        current_price = float(latest["Close"])
        prev_close = float(prev["Close"]) if prev is not None else current_price
        change = current_price - prev_close
        change_pct = (change / prev_close * 100) if prev_close else 0.0

        return {
            "ticker": ticker,
            "label": ASSET_LABELS.get(ticker, ticker),
            "current_price": round(current_price, 4),
            "prev_close": round(prev_close, 4),
            "change": round(change, 4),
            "change_pct": round(change_pct, 4),
            "open": round(float(latest["Open"]), 4),
            "high": round(float(latest["High"]), 4),
            "low": round(float(latest["Low"]), 4),
            "volume": int(latest.get("Volume", 0) or 0),
            "currency": getattr(info, "currency", "USD"),
            "market_state": getattr(info, "market_state", "unknown"),
            "source": "yfinance",
        }

    async def get_history(
        self,
        ticker: str,
        period: str = "1mo",
        interval: str = "1d",
    ) -> dict[str, Any]:
        """Return OHLCV history for *ticker* over *period*."""
        try:
            import yfinance as yf
        except ImportError as exc:
            raise ToolError("yfinance is not installed.") from exc

        if period not in VALID_PERIODS:
            raise ToolError(
                f"Invalid period '{period}'. Valid values: {', '.join(sorted(VALID_PERIODS))}"
            )
        if interval not in VALID_INTERVALS:
            raise ToolError(
                f"Invalid interval '{interval}'. Valid values: {', '.join(sorted(VALID_INTERVALS))}"
            )

        try:
            t = yf.Ticker(ticker)
            hist = t.history(period=period, interval=interval, auto_adjust=True)
        except Exception as exc:  # noqa: BLE001
            raise ToolError(f"yfinance history error for {ticker}: {exc}") from exc

        if hist.empty:
            raise ToolError(f"No historical data returned for ticker '{ticker}'.")

        rows = []
        for ts, row in hist.iterrows():
            rows.append(
                {
                    "date": str(ts.date() if hasattr(ts, "date") else ts),
                    "open": round(float(row["Open"]), 4),
                    "high": round(float(row["High"]), 4),
                    "low": round(float(row["Low"]), 4),
                    "close": round(float(row["Close"]), 4),
                    "volume": int(row.get("Volume", 0) or 0),
                }
            )

        # Summary statistics
        closes = [r["close"] for r in rows]
        highs = [r["high"] for r in rows]
        lows = [r["low"] for r in rows]

        return {
            "ticker": ticker,
            "label": ASSET_LABELS.get(ticker, ticker),
            "period": period,
            "interval": interval,
            "bars": len(rows),
            "summary": {
                "period_high": round(max(highs), 4),
                "period_low": round(min(lows), 4),
                "period_open": rows[0]["open"] if rows else None,
                "period_close": rows[-1]["close"] if rows else None,
                "period_change_pct": (
                    round((rows[-1]["close"] - rows[0]["open"]) / rows[0]["open"] * 100, 2)
                    if rows
                    else 0.0
                ),
            },
            "data": rows,
            "source": "yfinance",
        }


# ── Alpha Vantage adapter ──────────────────────────────────────────────────────

class _AlphaVantageAdapter:
    """Alpha Vantage REST adapter for commodity prices.

    Free tier: 25 API calls/day, 5 calls/minute.
    Docs: https://www.alphavantage.co/documentation/
    """

    BASE_URL = "https://www.alphavantage.co/query"
    DEFAULT_TIMEOUT = 15.0

    # AV function codes for common commodities
    AV_FUNCTION_MAP: dict[str, str] = {
        "WTI": "WTI",
        "BRENT": "BRENT",
        "NATURAL_GAS": "NATURAL_GAS",
        "COPPER": "COPPER",
        "ALUMINUM": "ALUMINUM",
        "WHEAT": "WHEAT",
        "CORN": "CORN",
        "COTTON": "COTTON",
        "SUGAR": "SUGAR",
        "COFFEE": "COFFEE",
        "ALL_COMMODITIES": "ALL_COMMODITIES",
    }

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def get_commodity(
        self,
        function: str,
        interval: str = "daily",
    ) -> dict[str, Any]:
        """Fetch commodity price series from Alpha Vantage."""
        if function not in self.AV_FUNCTION_MAP:
            raise ToolError(
                f"Unknown Alpha Vantage function '{function}'. "
                f"Available: {', '.join(self.AV_FUNCTION_MAP)}"
            )

        params = {
            "function": function,
            "interval": interval,
            "apikey": self._api_key,
        }

        log.debug("Alpha Vantage request", function=function, interval=interval)

        async with httpx.AsyncClient(timeout=self.DEFAULT_TIMEOUT) as client:
            try:
                resp = await client.get(self.BASE_URL, params=params)
                resp.raise_for_status()
            except httpx.TimeoutException as exc:
                raise ToolError(f"Alpha Vantage request timed out: {exc}") from exc
            except httpx.HTTPStatusError as exc:
                raise ToolError(
                    f"Alpha Vantage returned HTTP {exc.response.status_code}"
                ) from exc
            except httpx.RequestError as exc:
                raise ToolError(f"Alpha Vantage network error: {exc}") from exc

        data = resp.json()

        # Check for API limit / error messages
        if "Information" in data:
            raise ToolError(f"Alpha Vantage API limit: {data['Information']}")
        if "Error Message" in data:
            raise ToolError(f"Alpha Vantage error: {data['Error Message']}")
        if "Note" in data:
            log.warning("Alpha Vantage rate limit note", note=data["Note"])

        return data


# ── Tool ───────────────────────────────────────────────────────────────────────

class CommodityDataFetcher(BaseTool):
    """Fetch real-time and historical commodity prices.

    Covers WTI Crude, Brent Crude, Gold, Silver, and Natural Gas.
    Primary data source: yfinance (no key required).
    Secondary data source: Alpha Vantage (key optional).
    """

    def __init__(self, alpha_vantage_key: str = "") -> None:
        self._yf = _YFinanceAdapter()
        self._av = _AlphaVantageAdapter(alpha_vantage_key) if alpha_vantage_key else None

    # ── BaseTool contract ──────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "get_commodity_price"

    @property
    def description(self) -> str:
        return (
            "Fetch current price, daily change, and optional price history for "
            "commodities including Crude Oil (WTI/Brent) and Gold (XAU). "
            "Use this to get real-time prices and identify recent price trends "
            "that correlate with geopolitical events. "
            f"Supported assets: {', '.join(sorted(TICKER_MAP.keys()))}."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "asset": {
                    "type": "string",
                    "description": (
                        "Asset to fetch. Accepts common names or ticker symbols. "
                        f"Examples: {', '.join(list(TICKER_MAP.keys())[:8])}. "
                        "Multiple assets can be fetched in one call using 'assets' instead."
                    ),
                },
                "assets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of assets to fetch in a single call. "
                        "Use this instead of 'asset' when you need multiple prices at once."
                    ),
                },
                "include_history": {
                    "type": "boolean",
                    "description": "Include recent price history (default: false).",
                    "default": False,
                },
                "period": {
                    "type": "string",
                    "description": (
                        "History lookback period (only used when include_history=true). "
                        f"Valid values: {', '.join(sorted(VALID_PERIODS))}. Default: '1mo'."
                    ),
                    "default": "1mo",
                },
                "interval": {
                    "type": "string",
                    "description": (
                        "Bar interval for history (only used when include_history=true). "
                        f"Valid values: {', '.join(sorted(VALID_INTERVALS))}. Default: '1d'."
                    ),
                    "default": "1d",
                },
            },
            # Either 'asset' or 'assets' must be provided
        }

    async def execute(
        self,
        asset: str | None = None,
        assets: list[str] | None = None,
        include_history: bool = False,
        period: str = "1mo",
        interval: str = "1d",
        **_: Any,
    ) -> str:
        """Fetch commodity price data and return formatted JSON."""
        # Normalise to a list of tickers
        raw_names: list[str] = []
        if assets:
            raw_names.extend(assets)
        if asset:
            raw_names.append(asset)

        if not raw_names:
            raise ToolError("Must specify 'asset' or 'assets'.")

        tickers = self._resolve_tickers(raw_names)

        results: list[dict[str, Any]] = []
        errors: list[str] = []

        for ticker in tickers:
            try:
                price_data = await self._yf.get_current_price(ticker)
                if include_history:
                    history = await self._yf.get_history(ticker, period=period, interval=interval)
                    price_data["history"] = history
                results.append(price_data)
            except ToolError as exc:
                errors.append(f"{ticker}: {exc}")
                log.warning("Price fetch failed", ticker=ticker, error=str(exc))

        if not results and errors:
            raise ToolError(
                f"All price fetches failed:\n" + "\n".join(errors)
            )

        output: dict[str, Any] = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "assets": results,
        }
        if errors:
            output["warnings"] = errors

        return json.dumps(output, indent=2, ensure_ascii=False)

    # ── Helpers ────────────────────────────────────────────────────────────

    def _resolve_tickers(self, names: list[str]) -> list[str]:
        """Map user-provided names/symbols to canonical yfinance tickers."""
        tickers: list[str] = []
        for name in names:
            normalised = name.lower().strip().replace(" ", "_").replace("-", "_")
            if normalised in TICKER_MAP:
                tickers.append(TICKER_MAP[normalised])
            elif name.upper() in {v for v in TICKER_MAP.values()}:
                tickers.append(name.upper())
            else:
                # Treat as a raw ticker symbol
                log.warning("Unknown asset name, using as raw ticker", name=name)
                tickers.append(name.upper())
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for t in tickers:
            if t not in seen:
                seen.add(t)
                unique.append(t)
        return unique
