"""
migraguard.report
~~~~~~~~~~~~~~~~~

Renders a list of :class:`~migraguard.rules.base.Finding` objects as either:

  * A rich, colorized terminal report (default).
  * A machine-readable JSON array (``--format json``).

The terminal report groups findings by severity (critical → high → medium → low)
and prints a summary panel with per-severity counts and a pass/fail verdict.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from typing import Literal

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich import box

from migraguard.rules.base import Finding, SEVERITY_ORDER


# Output format literal type
OutputFormat = Literal["text", "json"]

# Severity → (Rich style, badge label)
_SEVERITY_STYLE: dict[str, tuple[str, str]] = {
    "critical": ("bold red",         "● CRITICAL"),
    "high":     ("red",              "▲ HIGH    "),
    "medium":   ("yellow",           "◆ MEDIUM  "),
    "low":      ("cyan",             "◇ LOW     "),
}

_SEVERITY_EMOJI: dict[str, str] = {
    "critical": "🔴",
    "high":     "🟠",
    "medium":   "🟡",
    "low":      "🔵",
}


def render(
    findings: list[Finding],
    format: OutputFormat = "text",
    *,
    console: Console | None = None,
) -> None:
    """
    Render *findings* to stdout.

    Parameters
    ----------
    findings:
        All findings collected across all scanned files.
    format:
        ``"text"`` for rich terminal output, ``"json"`` for JSON array.
    console:
        Optional :class:`rich.console.Console` instance (useful for testing).
    """
    if format == "json":
        _render_json(findings)
    else:
        _render_text(findings, console=console)


# ---------------------------------------------------------------------------
# JSON renderer
# ---------------------------------------------------------------------------

def _render_json(findings: list[Finding]) -> None:
    payload = [f.to_dict() for f in findings]
    print(json.dumps(payload, indent=2))


# ---------------------------------------------------------------------------
# Rich terminal renderer
# ---------------------------------------------------------------------------

def _render_text(findings: list[Finding], *, console: Console | None = None) -> None:
    if console is None:
        console = Console(stderr=False, highlight=False, legacy_windows=False)

    console.print()
    console.print(
        Panel.fit(
            "[bold white]MigraGuard[/bold white] — SQL Migration Static Analysis",
            border_style="bright_blue",
            padding=(0, 2),
        )
    )
    console.print()

    if not findings:
        console.print(
            Panel(
                Text("✅  No findings — migration looks safe!", style="bold green"),
                border_style="green",
                padding=(0, 2),
            )
        )
        console.print()
        return

    # Group by severity (ordered most → least severe)
    by_severity: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        by_severity[f.severity].append(f)

    ordered_severities = sorted(
        by_severity.keys(),
        key=lambda s: SEVERITY_ORDER.get(s, -1),
        reverse=True,
    )

    for severity in ordered_severities:
        style, badge = _SEVERITY_STYLE[severity]
        emoji = _SEVERITY_EMOJI[severity]
        group = by_severity[severity]

        console.print(Rule(f"{emoji}  {badge.strip()} ({len(group)})", style=style))
        console.print()

        for i, finding in enumerate(group, 1):
            _render_finding(console, finding, i, style)

    # Summary table
    _render_summary(console, findings, by_severity)


def _render_finding(
    console: Console,
    finding: Finding,
    index: int,
    severity_style: str,
) -> None:
    """Render a single finding as a panel with structured fields."""

    # Header line
    header = Text()
    header.append(f"[{index}] ", style="dim")
    header.append(finding.rule_id, style="bold " + severity_style)
    header.append("  ")
    if finding.file_path:
        header.append(finding.file_path, style="dim underline")
        header.append(f"  line {finding.line_number}", style="dim")
    else:
        header.append(f"line {finding.line_number}", style="dim")

    # Body
    body = Text()
    body.append("Explanation\n", style="bold white")
    body.append(finding.explanation + "\n\n", style="white")
    body.append("Suggested fix\n", style="bold green")
    body.append(finding.suggested_fix + "\n\n", style="green")
    body.append("Statement\n", style="bold dim")

    # Truncate very long SQL for display
    stmt = finding.statement.strip()
    if len(stmt) > 300:
        stmt = stmt[:297] + "..."
    body.append(stmt, style="dim italic")

    console.print(
        Panel(
            body,
            title=header,
            title_align="left",
            border_style=severity_style,
            padding=(1, 2),
        )
    )
    console.print()


def _render_summary(
    console: Console,
    findings: list[Finding],
    by_severity: dict[str, list[Finding]],
) -> None:
    """Render the summary table with per-severity counts and verdict."""
    table = Table(box=box.ROUNDED, show_header=True, header_style="bold white")
    table.add_column("Severity",  style="bold", min_width=10)
    table.add_column("Count",     justify="right", min_width=6)

    for severity in ["critical", "high", "medium", "low"]:
        count = len(by_severity.get(severity, []))
        if count == 0:
            continue
        style, _ = _SEVERITY_STYLE[severity]
        table.add_row(
            Text(severity.upper(), style=style),
            Text(str(count), style=style),
        )

    table.add_section()
    table.add_row("TOTAL", str(len(findings)))

    blocking = any(f.is_blocking() for f in findings)
    verdict_text = (
        Text("❌  FAILED — high/critical findings detected", style="bold red")
        if blocking
        else Text("⚠️  WARNINGS — review medium/low findings", style="bold yellow")
    )

    console.print(Rule("Summary", style="bright_blue"))
    console.print(table)
    console.print()
    console.print(verdict_text)
    console.print()
