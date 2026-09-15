"""
migraguard.rules.base
~~~~~~~~~~~~~~~~~~~~~

Shared base classes and data structures used by every rule.

Each concrete rule must:
  1. Subclass :class:`BaseRule`
  2. Set a unique :attr:`RULE_ID` and :attr:`DESCRIPTION` class attribute
  3. Implement :meth:`check` — receive the full statement list + context,
     return a (possibly empty) list of :class:`Finding` objects.

Rules are stateless — a fresh instance is used per file scan.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from migraguard.parser import MigrationContext, ParsedStatement

# All valid severity levels, ordered from least to most severe.
Severity = Literal["low", "medium", "high", "critical"]

SEVERITY_ORDER: dict[Severity, int] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}


@dataclass
class Finding:
    """
    A single rule violation found in a migration file.

    Attributes
    ----------
    rule_id:
        Unique identifier for the rule that produced this finding (e.g. ``"MG001"``).
    severity:
        One of ``"low"``, ``"medium"``, ``"high"``, ``"critical"``.
    statement:
        The raw SQL text of the offending statement.
    line_number:
        Approximate 1-based line number in the source file.
    explanation:
        Human-readable description of *why* this is risky.
    suggested_fix:
        Actionable recommendation for how to make the migration safe.
    file_path:
        Source file path (set by the scanner, not the rule).
    """

    rule_id: str
    severity: Severity
    statement: str
    line_number: int
    explanation: str
    suggested_fix: str
    file_path: str = ""  # injected by the scanner after rule.check() returns

    def is_blocking(self) -> bool:
        """Return ``True`` if this finding should cause a non-zero exit code."""
        return SEVERITY_ORDER[self.severity] >= SEVERITY_ORDER["high"]

    def to_dict(self) -> dict:
        """Serialize to a plain dict (used for JSON output)."""
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "statement": self.statement,
            "line_number": self.line_number,
            "explanation": self.explanation,
            "suggested_fix": self.suggested_fix,
            "file_path": self.file_path,
        }


class BaseRule(ABC):
    """Abstract base class for all MigraGuard rules."""

    #: Unique rule identifier, e.g. ``"MG001"``
    RULE_ID: str = ""

    #: Short human-readable description of what this rule detects.
    DESCRIPTION: str = ""

    @abstractmethod
    def check(
        self,
        statements: list[ParsedStatement],
        context: MigrationContext,
    ) -> list[Finding]:
        """
        Analyse *statements* (and *context*) and return zero or more findings.

        Parameters
        ----------
        statements:
            All :class:`~migraguard.parser.ParsedStatement` objects from the
            migration file, in source order.
        context:
            :class:`~migraguard.parser.MigrationContext` with aggregated
            cross-statement metadata (indexes created, tables touched, etc.).

        Returns
        -------
        list[Finding]
            Empty list if the migration passes this rule.
        """
        ...
