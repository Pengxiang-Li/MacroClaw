"""Investment brief formatter — Phase 4 output rendering.

Parses the LLM's JSON output into a typed InvestmentBrief and renders
it as a rich terminal report.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from macroclaw.logging import get_logger

log = get_logger(__name__, subsystem="output")

console = Console()

SIGNAL_COLORS = {"BULLISH": "green", "BEARISH": "red", "NEUTRAL": "yellow"}
RISK_COLORS = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red"}


# ── Data model ─────────────────────────────────────────────────────────────────

@dataclass
class KeyEvent:
    event: str
    location: str = ""
    date: str = ""
    market_impact: str = ""


@dataclass
class CommodityAction:
    asset: str
    ticker: str = ""
    current_price: float = 0.0
    currency: str = "USD"
    change_pct_1d: float = 0.0
    period_trend: str = ""
    geopolitical_correlation: str = ""


@dataclass
class InvestmentBrief:
    executive_summary: str = ""
    key_events: list[KeyEvent] = field(default_factory=list)
    commodity_action: list[CommodityAction] = field(default_factory=list)
    risk_level: str = "UNKNOWN"
    risk_rationale: str = ""
    signals: dict[str, str] = field(default_factory=dict)
    investment_strategy: str = ""
    recommendations: list[str] = field(default_factory=list)
    data_quality_notes: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


def parse_brief(llm_text: str) -> InvestmentBrief:
    """Extract and parse the JSON investment brief from raw LLM output.

    Handles cases where the model wraps JSON in markdown fences.
    Falls back to a minimal brief on parse failure.
    """
    text = llm_text.strip()

    # Strip markdown code fences if present
    fenced = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if fenced:
        text = fenced.group(1).strip()

    # Find the outermost JSON object
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        log.warning("No JSON object found in LLM output", preview=llm_text[:200])
        return InvestmentBrief(executive_summary=llm_text)

    try:
        data: dict[str, Any] = json.loads(text[start:end])
    except json.JSONDecodeError as exc:
        log.warning("JSON parse failed", error=str(exc), preview=text[:200])
        return InvestmentBrief(executive_summary=llm_text)

    brief = InvestmentBrief(raw=data)
    brief.executive_summary = data.get("executive_summary", "")
    brief.risk_level = data.get("risk_level", "UNKNOWN").upper()
    brief.risk_rationale = data.get("risk_rationale", "")
    brief.signals = {k.upper(): v.upper() for k, v in data.get("signals", {}).items()}
    brief.investment_strategy = data.get("investment_strategy", "")
    brief.recommendations = data.get("recommendations", [])
    brief.data_quality_notes = data.get("data_quality_notes", "")

    for ev in data.get("key_events", []):
        brief.key_events.append(
            KeyEvent(
                event=ev.get("event", ""),
                location=ev.get("location", ""),
                date=ev.get("date", ""),
                market_impact=ev.get("market_impact", ""),
            )
        )

    for ca in data.get("commodity_action", []):
        brief.commodity_action.append(
            CommodityAction(
                asset=ca.get("asset", ""),
                ticker=ca.get("ticker", ""),
                current_price=float(ca.get("current_price") or 0),
                currency=ca.get("currency", "USD"),
                change_pct_1d=float(ca.get("change_pct_1d") or 0),
                period_trend=ca.get("period_trend", ""),
                geopolitical_correlation=ca.get("geopolitical_correlation", ""),
            )
        )

    return brief


def format_brief(brief: InvestmentBrief) -> None:
    """Render an InvestmentBrief to the terminal using Rich."""

    console.print()
    console.rule("[bold cyan]MacroClaw Investment Brief[/bold cyan]")
    console.print()

    # ── Executive Summary ──────────────────────────────────────────────────
    console.print(
        Panel(
            brief.executive_summary or "(no summary)",
            title="[bold]Executive Summary[/bold]",
            border_style="cyan",
        )
    )

    # ── Risk Level ─────────────────────────────────────────────────────────
    risk_color = RISK_COLORS.get(brief.risk_level, "white")
    risk_text = Text()
    risk_text.append("Overall Risk: ", style="bold")
    risk_text.append(brief.risk_level, style=f"bold {risk_color}")
    if brief.risk_rationale:
        risk_text.append(f"  —  {brief.risk_rationale}", style="dim")
    console.print(Panel(risk_text, title="[bold]Risk Assessment[/bold]", border_style=risk_color))

    # ── Signals ────────────────────────────────────────────────────────────
    if brief.signals:
        sig_table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold magenta")
        sig_table.add_column("Asset", style="bold", min_width=16)
        sig_table.add_column("Signal", min_width=10)
        for asset, signal in brief.signals.items():
            color = SIGNAL_COLORS.get(signal, "white")
            sig_table.add_row(asset.replace("_", " "), f"[{color}]{signal}[/{color}]")
        console.print(Panel(sig_table, title="[bold]Directional Signals[/bold]", border_style="magenta"))

    # ── Commodity Action ───────────────────────────────────────────────────
    if brief.commodity_action:
        com_table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold yellow")
        com_table.add_column("Asset", style="bold", min_width=20)
        com_table.add_column("Price", justify="right", min_width=10)
        com_table.add_column("1D Change", justify="right", min_width=10)
        com_table.add_column("Trend / Correlation", min_width=40)
        for ca in brief.commodity_action:
            chg = ca.change_pct_1d
            chg_color = "green" if chg >= 0 else "red"
            chg_str = f"[{chg_color}]{chg:+.2f}%[/{chg_color}]"
            price_str = f"{ca.currency} {ca.current_price:,.2f}" if ca.current_price else "N/A"
            trend = ca.period_trend or ca.geopolitical_correlation or ""
            com_table.add_row(ca.asset, price_str, chg_str, trend[:60])
        console.print(Panel(com_table, title="[bold]Commodity Action[/bold]", border_style="yellow"))

    # ── Key Events ─────────────────────────────────────────────────────────
    if brief.key_events:
        events_text = Text()
        for i, ev in enumerate(brief.key_events, 1):
            loc = f" [{ev.location}]" if ev.location else ""
            dt = f" ({ev.date})" if ev.date else ""
            events_text.append(f"{i}. ", style="bold")
            events_text.append(f"{ev.event}{loc}{dt}\n")
            if ev.market_impact:
                events_text.append(f"   → {ev.market_impact}\n", style="dim")
        console.print(Panel(events_text, title="[bold]Key Events Tracker[/bold]", border_style="blue"))

    # ── Investment Strategy ────────────────────────────────────────────────
    if brief.investment_strategy or brief.recommendations:
        strat_text = Text()
        if brief.investment_strategy:
            strat_text.append(brief.investment_strategy + "\n\n")
        for i, rec in enumerate(brief.recommendations, 1):
            strat_text.append(f"  {i}. {rec}\n", style="bold green")
        console.print(Panel(strat_text, title="[bold]Investment Strategy[/bold]", border_style="green"))

    # ── Data Quality Notes ─────────────────────────────────────────────────
    if brief.data_quality_notes:
        console.print(
            Panel(
                Text(brief.data_quality_notes, style="dim"),
                title="[dim]Data Quality Notes[/dim]",
                border_style="dim",
            )
        )

    console.rule()
    console.print()
