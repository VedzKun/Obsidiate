"""
migraguard.cli
~~~~~~~~~~~~~~

Command-line interface for MigraGuard.

Usage
-----
  migraguard scan <path> [--format text|json]

  <path>  A single .sql file or a directory (scanned recursively for *.sql).

Exit codes
----------
  0  No high or critical findings.
  1  One or more high or critical findings were detected.
  2  Usage/input error (invalid path, parse failure, etc.).
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console

from migraguard import __version__
from migraguard.parser import parse_file
from migraguard.report import render
from migraguard.rules.base import Finding
from migraguard.rules.locking import LockingOperationRule
from migraguard.rules.missing_index import MissingIndexRule
from migraguard.rules.reversibility import ReversibilityRule


# All active rules — add new rules here to plug them in automatically.
_ALL_RULES = [
    LockingOperationRule(),
    MissingIndexRule(),
    ReversibilityRule(),
]


def _collect_sql_files(path: Path) -> list[Path]:
    """Return all .sql files reachable from *path* (file or directory)."""
    if path.is_file():
        if path.suffix.lower() != ".sql":
            raise click.BadParameter(
                f"File '{path}' does not have a .sql extension.",
                param_hint="'PATH'",
            )
        return [path]
    if path.is_dir():
        files = sorted(path.rglob("*.sql"))
        if not files:
            raise click.BadParameter(
                f"No .sql files found under '{path}'.",
                param_hint="'PATH'",
            )
        return files
    raise click.BadParameter(
        f"'{path}' is neither a file nor a directory.",
        param_hint="'PATH'",
    )


def _scan_file(file_path: Path) -> list[Finding]:
    """Parse *file_path* and run all rules against it. Returns findings list."""
    try:
        ctx = parse_file(file_path)
    except ValueError as exc:
        click.echo(f"[ERROR] Cannot parse {file_path}: {exc}", err=True)
        return []

    findings: list[Finding] = []
    for rule in _ALL_RULES:
        rule_findings = rule.check(ctx.statements, ctx)
        for f in rule_findings:
            f.file_path = str(file_path)
        findings.extend(rule_findings)
    return findings


# ---------------------------------------------------------------------------
# Click commands
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(__version__, prog_name="migraguard")
def main() -> None:
    """MigraGuard — SQL migration static analysis tool."""


@main.command("scan")
@click.argument("path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    show_default=True,
    help="Output format: human-readable text or machine-readable JSON.",
)
def scan(path: Path, output_format: str) -> None:
    """
    Scan a migration file or directory for risky SQL operations.

    PATH can be a single .sql file or a directory (searched recursively).

    \b
    Exit codes:
      0  No high or critical findings.
      1  One or more high or critical findings detected.
      2  Input/usage error.
    """
    if sys.platform == "win32":
        try:
            if sys.stdout and hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8")
            if sys.stderr and hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    console = Console(stderr=False, highlight=False, legacy_windows=False)

    try:
        sql_files = _collect_sql_files(path)
    except click.BadParameter as exc:
        click.echo(str(exc), err=True)
        sys.exit(2)

    if output_format == "text":
        console.print(
            f"\n[dim]Scanning [bold]{len(sql_files)}[/bold] file(s)…[/dim]\n"
        )

    all_findings: list[Finding] = []
    for sql_file in sql_files:
        findings = _scan_file(sql_file)
        all_findings.extend(findings)

    render(all_findings, format=output_format, console=console)  # type: ignore[arg-type]

    # Exit code: 1 if any blocking (high/critical) finding exists.
    if any(f.is_blocking() for f in all_findings):
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()

