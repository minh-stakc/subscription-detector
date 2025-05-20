#!/usr/bin/env python3
"""
Subscription Leak Detector -- CLI entry point.

Usage:
    python main.py seed [--rows N]
    python main.py ingest <FILE>
    python main.py run
    python main.py summary
    python main.py report [--format html|csv] [--output PATH]
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

# Ensure project root is on sys.path so imports work when invoked directly
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import CURRENCY_SYMBOL
from db.models import init_db, Session
from pipeline.processor import run_seed, run_ingest, run_detection
from reporting.summary import generate_summary
from reporting.export import export_html, export_csv
from utils import fmt_currency

console = Console()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
def cli(verbose: bool) -> None:
    """Subscription Leak Detector -- find forgotten and duplicate subscriptions."""
    _setup_logging(verbose)


# ---------------------------------------------------------------------------
# seed
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--rows", default=2000, show_default=True, help="Number of synthetic transactions")
def seed(rows: int) -> None:
    """Generate synthetic transaction data and load into the database."""
    console.print(f"[bold]Seeding database with ~{rows} transactions...[/bold]")
    n = run_seed(rows)
    console.print(f"[green]Loaded {n} new transactions.[/green]")


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------

@cli.command()
@click.argument("file", type=click.Path(exists=True))
def ingest(file: str) -> None:
    """Ingest a CSV or JSON transaction file."""
    console.print(f"[bold]Ingesting {file}...[/bold]")
    n = run_ingest(file)
    console.print(f"[green]Loaded {n} new transactions.[/green]")


# ---------------------------------------------------------------------------
# run (detection pipeline)
# ---------------------------------------------------------------------------

@cli.command()
def run() -> None:
    """Run the full detection pipeline on existing data."""
    init_db()
    console.print("[bold]Running detection pipeline...[/bold]")
    result = run_detection()

    table = Table(title="Detection Results", show_header=False, pad_edge=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="bold")
    table.add_row("Subscriptions detected", str(result["subscriptions_detected"]))
    table.add_row("Duplicate pairs found", str(result["duplicate_pairs"]))
    table.add_row("Anomalies flagged", str(result["anomalies"]))
    table.add_row("Alerts generated", str(result["alerts_generated"]))
    console.print(table)


# ---------------------------------------------------------------------------
# summary
# ---------------------------------------------------------------------------

@cli.command()
def summary() -> None:
    """Display a spending summary in the terminal."""
    init_db()
    session = Session()
    try:
        data = generate_summary(session)
    finally:
        session.close()

    if data["total_transactions"] == 0:
        console.print("[yellow]No transactions in the database. Run 'seed' or 'ingest' first.[/yellow]")
        return

    # -- header panel -----------------------------------------------------
    header = Text()
    header.append("Subscription Leak Detector Summary\n", style="bold underline")
    header.append(
        f"Transactions: {data['total_transactions']}  |  "
        f"Period: {data['date_range']['first']} to {data['date_range']['last']}\n"
    )
    header.append(
        f"Active subscriptions: {data['subscription_count']}  |  "
        f"Est. annual cost: {fmt_currency(data['estimated_annual_cost'])}\n"
    )
    console.print(Panel(header, border_style="blue"))

    # -- subscription table -----------------------------------------------
    if data["active_subscriptions"]:
        tbl = Table(title="Active Subscriptions")
        tbl.add_column("Merchant", style="cyan")
        tbl.add_column("Freq")
        tbl.add_column("Amount", justify="right")
        tbl.add_column("Annual", justify="right", style="bold")
        tbl.add_column("Regularity", justify="right")
        tbl.add_column("Last Seen")

        for s in data["active_subscriptions"]:
            tbl.add_row(
                s["merchant"],
                s["frequency"],
                fmt_currency(s["median_amount"]),
                fmt_currency(s["annual_cost"]),
                f"{s['regularity']:.0%}",
                str(s["last_seen"]),
            )
        console.print(tbl)

    # -- alert counts -----------------------------------------------------
    sev = data["alerts_by_severity"]
    total_alerts = sum(sev.values())
    if total_alerts:
        alert_text = Text()
        alert_text.append(f"Total alerts: {total_alerts}  (")
        alert_text.append(f"HIGH: {sev.get('high', 0)}", style="bold red")
        alert_text.append(f"  MEDIUM: {sev.get('medium', 0)}", style="bold yellow")
        alert_text.append(f"  LOW: {sev.get('low', 0)}", style="bold green")
        alert_text.append(")")
        console.print(Panel(alert_text, title="Alerts", border_style="red"))


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--format", "fmt", type=click.Choice(["html", "csv"]), default="html", show_default=True,
)
@click.option("--output", "-o", default=None, help="Output file path")
def report(fmt: str, output: str | None) -> None:
    """Export a report (HTML or CSV)."""
    init_db()
    if fmt == "html":
        path = export_html(output)
    else:
        path = export_csv(output)
    console.print(f"[green]Report written to {path}[/green]")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    cli()
