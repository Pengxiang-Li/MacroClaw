"""MacroClaw CLI entry point."""

from __future__ import annotations

import asyncio
import subprocess
import sys

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from macroclaw import __version__
from macroclaw.agents.agent_loop import AgentLoop
from macroclaw.agents.tool_registry import ToolRegistry
from macroclaw.config import load_config
from macroclaw.logging import get_logger, setup_logging
from macroclaw.memory.manager import MemoryManager
from macroclaw.output.formatter import format_brief
from macroclaw.tools.commodity_data_fetcher import CommodityDataFetcher
from macroclaw.tools.geopolitical_news_fetcher import GeopoliticalNewsFetcher

console = Console()
log = get_logger(__name__, subsystem="cli")

DEFAULT_QUERY = (
    "Analyse the current global geopolitical environment and its impact on "
    "Crude Oil (WTI and Brent) and Gold prices. Provide a full investment brief "
    "with directional signals and actionable strategy recommendations."
)


def _build_registry(config) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(GeopoliticalNewsFetcher(news_api_key=config.news_api_key))
    registry.register(CommodityDataFetcher(alpha_vantage_key=config.alpha_vantage_api_key))
    return registry


@click.group(invoke_without_command=True)
@click.version_option(__version__, "--version", "-V")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """MacroClaw — macroeconomic and geopolitical investment assistant."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(analyse)


@cli.command()
@click.argument("query", default=DEFAULT_QUERY, required=False)
@click.option("--model", "-m", default=None, help="Override the model (e.g. claude-opus-4-6).")
@click.option("--max-turns", "-t", default=None, type=int, help="Override max agent turns.")
@click.option("--no-memory", is_flag=True, default=False, help="Disable session memory.")
@click.option("--log-level", default=None, help="DEBUG|INFO|WARNING|ERROR.")
@click.option("--json-out", is_flag=True, default=False, help="Print raw JSON brief to stdout.")
def analyse(
    query: str,
    model: str | None,
    max_turns: int | None,
    no_memory: bool,
    log_level: str | None,
    json_out: bool,
) -> None:
    """Run a macroeconomic analysis and print a structured investment brief."""
    asyncio.run(
        _run_analyse(
            query=query,
            model_override=model,
            max_turns_override=max_turns,
            memory_disabled=no_memory,
            log_level_override=log_level,
            json_out=json_out,
        )
    )


async def _run_analyse(
    query: str,
    model_override: str | None,
    max_turns_override: int | None,
    memory_disabled: bool,
    log_level_override: str | None,
    json_out: bool,
) -> None:
    config = load_config()

    setup_logging(
        level=log_level_override or config.log_level,
        log_file=config.log_file,
    )

    missing = config.validate_required()
    if missing:
        console.print(
            f"[red]Error:[/red] Missing required env vars: {', '.join(missing)}\n"
            "Copy .env.example to .env and set at least one of:\n"
            "  DEERAPI_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY"
        )
        sys.exit(1)

    log.info("MacroClaw starting", version=__version__, model=config.model)

    registry = _build_registry(config)
    memory = MemoryManager(
        enabled=not memory_disabled and config.memory_enabled,
        persist_path=config.memory_path + "/session.json" if config.memory_enabled else None,
    )
    agent = AgentLoop(config=config, registry=registry, memory=memory)

    console.print(f"\n[bold cyan]MacroClaw[/bold cyan] v{__version__}")
    console.print(f"[dim]Model:[/dim] {config.model}")
    console.print(f"[dim]Query:[/dim] {query[:120]}{'...' if len(query) > 120 else ''}\n")

    brief = None
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console, transient=True) as progress:
        task = progress.add_task("Analysing macro environment…", total=None)
        try:
            brief = await agent.run(query)
        except RuntimeError as exc:
            console.print(f"[red]Agent error:[/red] {exc}")
            sys.exit(1)
        finally:
            progress.remove_task(task)

    memory.save_to_disk()

    if json_out and brief and brief.raw:
        import json
        console.print_json(json.dumps(brief.raw))
    elif brief:
        format_brief(brief)
    else:
        console.print("[red]No brief generated.[/red]")


@cli.command()
def dashboard() -> None:
    """Launch the MacroClaw Streamlit dashboard."""
    import os
    dashboard_path = os.path.join(
        os.path.dirname(__file__), "dashboard", "app.py"
    )
    console.print(f"\n[bold cyan]MacroClaw Dashboard[/bold cyan] — launching Streamlit…")
    console.print("[dim]Press Ctrl+C to stop.[/dim]\n")
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", dashboard_path, "--server.headless=false"],
        check=False,
    )


@cli.command()
def config_check() -> None:
    """Validate the current MacroClaw configuration."""
    cfg = load_config()
    setup_logging(level=cfg.log_level)
    console.print("\n[bold]MacroClaw Configuration[/bold]\n")
    console.print(f"  Provider:       {cfg.active_provider}")
    console.print(f"  Model:          {cfg.model}")
    console.print(f"  Max tokens:     {cfg.max_tokens}")
    console.print(f"  Max turns:      {cfg.max_turns}")
    console.print(f"  Memory enabled: {cfg.memory_enabled}")
    console.print(f"  Memory path:    {cfg.memory_path}")
    console.print(f"  Log level:      {cfg.log_level}")
    console.print()

    missing = cfg.validate_required()
    if missing:
        console.print(f"  [red]MISSING:[/red] {', '.join(missing)}")
    else:
        provider = cfg.active_provider
        if provider == "deerapi":
            console.print("  [green]✓[/green] DEERAPI_KEY set")
        elif provider == "anthropic":
            console.print("  [green]✓[/green] ANTHROPIC_API_KEY set")
        else:
            console.print("  [green]✓[/green] OPENAI_API_KEY set")

    console.print(
        f"  {'[green]✓[/green]' if cfg.has_news_api() else '[yellow]○[/yellow]'} "
        f"NEWS_API_KEY {'set' if cfg.has_news_api() else 'not set (GDELT used)'}"
    )
    console.print(
        f"  {'[green]✓[/green]' if cfg.has_alpha_vantage() else '[yellow]○[/yellow]'} "
        f"ALPHA_VANTAGE_API_KEY {'set' if cfg.has_alpha_vantage() else 'not set (yfinance used)'}"
    )
    console.print()


if __name__ == "__main__":
    cli()
