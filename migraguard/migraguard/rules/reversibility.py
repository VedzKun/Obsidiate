"""
migraguard.rules.reversibility
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Rule MG003 — Irreversible Operation Detection.

Flags two categories of reversibility risk:

  1. **Destructive statements** — DROP TABLE (critical) and DROP COLUMN (high).
     These are irreversible once committed and data cannot be recovered from
     the migration itself.

  2. **No down migration** — Any migration containing a DROP statement that
     has no corresponding rollback path.  Detected via:
       - ``-- Down`` / ``-- +migrate Down`` / ``-- !Down`` inline comment marker
       - Sibling file whose name contains ``down``, ``rollback``, or ``revert``

sqlglot v30 AST notes:
  - DROP TABLE is an exp.Drop node with kind="TABLE" and tables=[Table(this=Identifier(...))]
  - DROP COLUMN is an exp.Drop action inside Alter with kind="COLUMN" and tables=[Column(this=Identifier(...))]
"""

from __future__ import annotations

from sqlglot import exp

from migraguard.parser import MigrationContext, ParsedStatement, StatementType
from migraguard.rules.base import BaseRule, Finding


class ReversibilityRule(BaseRule):
    """Detect irreversible DROP operations and missing rollback definitions."""

    RULE_ID = "MG003"
    DESCRIPTION = (
        "Flags DROP TABLE / DROP COLUMN statements and any destructive migration "
        "without a corresponding down-migration definition."
    )

    def check(
        self,
        statements: list[ParsedStatement],
        context: MigrationContext,
    ) -> list[Finding]:
        findings: list[Finding] = []
        has_destructive = False

        for stmt in statements:
            # ── DROP TABLE ────────────────────────────────────────────
            if stmt.statement_type == StatementType.DROP_TABLE:
                has_destructive = True
                table_names = self._extract_table_names_from_drop(stmt.ast)
                for table_name in table_names:
                    findings.append(
                        Finding(
                            rule_id=self.RULE_ID,
                            severity="critical",
                            statement=stmt.raw_sql,
                            line_number=stmt.line_number,
                            explanation=(
                                f"DROP TABLE{' ' + table_name if table_name else ''} is irreversible. "
                                f"All data in the table will be permanently lost once this migration "
                                f"is committed. There is no automatic way to recover the data from the "
                                f"migration itself."
                            ),
                            suggested_fix=(
                                f"Before dropping, archive the data:\n"
                                f"  CREATE TABLE {table_name or '<table>'}_archive AS "
                                f"SELECT * FROM {table_name or '<table>'};\n"
                                f"Or rename instead of dropping to allow recovery:\n"
                                f"  ALTER TABLE {table_name or '<table>'} RENAME TO "
                                f"{table_name or '<table>'}_deprecated_YYYYMMDD;\n"
                                f"Ensure a down migration exists that recreates the table structure."
                            ),
                        )
                    )
                if not table_names: # Fallback if no table names found
                    findings.append(
                        Finding(
                            rule_id=self.RULE_ID,
                            severity="critical",
                            statement=stmt.raw_sql,
                            line_number=stmt.line_number,
                            explanation=(
                                f"DROP TABLE is irreversible. "
                                f"All data in the table will be permanently lost once this migration "
                                f"is committed. There is no automatic way to recover the data from the "
                                f"migration itself."
                            ),
                            suggested_fix=(
                                f"Before dropping, archive the data:\n"
                                f"  CREATE TABLE <table>_archive AS "
                                f"SELECT * FROM <table>;\n"
                                f"Or rename instead of dropping to allow recovery:\n"
                                f"  ALTER TABLE <table> RENAME TO "
                                f"<table>_deprecated_YYYYMMDD;\n"
                                f"Ensure a down migration exists that recreates the table structure."
                            ),
                        )
                    )

            # ── DROP COLUMN ───────────────────────────────────────────
            elif stmt.statement_type == StatementType.ALTER_TABLE:
                drop_col_findings = self._check_drop_column(stmt)
                if drop_col_findings:
                    has_destructive = True
                    findings.extend(drop_col_findings)

        # ── No down migration for destructive migration ───────────────
        if has_destructive and not context.has_down_migration:
            findings.append(
                Finding(
                    rule_id=self.RULE_ID,
                    severity="high",
                    statement="(entire migration file)",
                    line_number=1,
                    explanation=(
                        "This migration contains destructive operations (DROP TABLE or DROP COLUMN) "
                        "but no down migration was detected. Without a rollback path, this change "
                        "cannot be reversed if deployment fails or data recovery is needed.\n"
                        "Searched for: inline `-- Down` / `-- +migrate Down` comment markers "
                        "and sibling files containing `down`, `rollback`, or `revert`."
                    ),
                    suggested_fix=(
                        "Add a `-- Down` section to this file with the inverse operations "
                        "(e.g. CREATE TABLE to reverse a DROP TABLE), or create a sibling file "
                        "named `<version>_down.sql` with the rollback SQL."
                    ),
                )
            )

        return findings

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_drop_column(self, stmt: ParsedStatement) -> list[Finding]:
        """Find DROP COLUMN actions inside ALTER TABLE statements."""
        findings: list[Finding] = []
        actions = stmt.ast.args.get("actions") or []
        table_name = self._extract_table_name_from_alter(stmt.ast)

        for action in actions:
            if isinstance(action, exp.Drop):
                kind = (action.args.get("kind") or "").upper()
                if kind == "COLUMN":
                    # In v30 Drop Column action, columns are in action.args["tables"] (yes, tables)
                    # each is a Column node
                    drop_targets = action.args.get("tables") or []
                    for target in drop_targets:
                        col_name = (
                            target.name.lower()
                            if hasattr(target, "name")
                            else "<column>"
                        )
                        findings.append(
                            Finding(
                                rule_id=self.RULE_ID,
                                severity="high",
                                statement=stmt.raw_sql,
                                line_number=stmt.line_number,
                                explanation=(
                                    f"DROP COLUMN `{col_name}` on table `{table_name or '<table>'}` "
                                    f"is irreversible. Any data stored in this column will be "
                                    f"permanently deleted when the migration runs."
                                ),
                                suggested_fix=(
                                    f"Consider a two-phase approach:\n"
                                    f"  Phase 1: Stop writing to `{col_name}` in application code "
                                    f"(deploy with the column still present).\n"
                                    f"  Phase 2: Drop the column once you are confident no rollback "
                                    f"is needed and the column is truly unused.\n"
                                    f"Also add a down migration that re-adds the column (with DEFAULT "
                                    f"NULL to avoid locking on rollback)."
                                ),
                            )
                        )

        return findings

    @staticmethod
    def _extract_table_names_from_drop(node: exp.Expression) -> list[str]:
        """Extract lowercased table names from a DROP TABLE node."""
        tables = node.args.get("tables") or []
        names = []
        for t in tables:
            names.append(t.name.lower() if hasattr(t, "name") else str(t).lower())
        return names

    @staticmethod
    def _extract_table_name_from_alter(node: exp.Expression) -> str:
        """Extract lowercased table name from an ALTER TABLE node."""
        tbl_node = node.args.get("this")
        if tbl_node is None:
            return ""
        return (
            tbl_node.name.lower() if hasattr(tbl_node, "name") else str(tbl_node).lower()
        )
