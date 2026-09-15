"""
migraguard.rules.locking
~~~~~~~~~~~~~~~~~~~~~~~~

Rule MG001 — Locking Operation Detection.

Flags ALTER TABLE statements that acquire an ACCESS EXCLUSIVE lock and hold
it long enough to cause visible production outages.

sqlglot v30 AST notes for ALTER TABLE:
  - The statement node is exp.Alter (kind="TABLE")
  - Actions live in node.args["actions"]
  - ADD COLUMN action   → exp.ColumnDef  (constraint kinds: NotNullColumnConstraint, DefaultColumnConstraint)
  - ALTER COLUMN action → exp.AlterColumn (dtype arg present for type changes)
  - ADD CONSTRAINT action → exp.AddConstraint
      .expressions = [Constraint(this=<name>, expressions=[ForeignKey|PrimaryKey|CheckColumnConstraint|...])]
  - NOT VALID lives on the root Alter node: node.args["not_valid"] == True

  ┌─────────────────────────────────────────────────────────┬──────────┐
  │ Pattern                                                 │ Severity │
  ├─────────────────────────────────────────────────────────┼──────────┤
  │ ALTER COLUMN … SET DATA TYPE (type change)              │ critical │
  │ ADD COLUMN … NOT NULL DEFAULT <non-null> (pre-PG11)     │ high     │
  │ ADD CONSTRAINT (FK/CHECK) without NOT VALID             │ high     │
  │ ADD PRIMARY KEY                                         │ high     │
  └─────────────────────────────────────────────────────────┴──────────┘
"""

from __future__ import annotations

from sqlglot import exp

from migraguard.parser import MigrationContext, ParsedStatement, StatementType
from migraguard.rules.base import BaseRule, Finding


class LockingOperationRule(BaseRule):
    """Detect ALTER TABLE operations that cause dangerous table-level locks."""

    RULE_ID = "MG001"
    DESCRIPTION = "Detects ALTER TABLE operations that acquire a long-held ACCESS EXCLUSIVE lock."

    def check(
        self,
        statements: list[ParsedStatement],
        context: MigrationContext,
    ) -> list[Finding]:
        findings: list[Finding] = []
        for stmt in statements:
            if stmt.statement_type != StatementType.ALTER_TABLE:
                continue
            findings.extend(self._check_alter_table(stmt))
        return findings

    # ------------------------------------------------------------------
    # Internal checkers
    # ------------------------------------------------------------------

    def _check_alter_table(self, stmt: ParsedStatement) -> list[Finding]:
        findings: list[Finding] = []
        actions = stmt.ast.args.get("actions") or []

        for action in actions:
            # ── ALTER COLUMN … SET DATA TYPE ──────────────────────────
            if isinstance(action, exp.AlterColumn):
                if action.args.get("dtype") is not None:
                    findings.append(
                        Finding(
                            rule_id=self.RULE_ID,
                            severity="critical",
                            statement=stmt.raw_sql,
                            line_number=stmt.line_number,
                            explanation=(
                                "ALTER COLUMN … SET DATA TYPE rewrites the entire table and holds "
                                "an ACCESS EXCLUSIVE lock for the full duration. On large tables "
                                "this can cause minutes of downtime."
                            ),
                            suggested_fix=(
                                "Create a new column with the desired type, backfill it in batches, "
                                "swap the column names in a short transaction, and drop the old column. "
                                "Alternatively, add `SET lock_timeout = '2s';` before this statement "
                                "so the migration fails fast rather than queuing all traffic."
                            ),
                        )
                    )

            # ── ADD COLUMN (ColumnDef in sqlglot v30) ─────────────────
            elif isinstance(action, exp.ColumnDef):
                finding = self._check_add_column(stmt, action)
                if finding:
                    findings.append(finding)

            # ── ADD CONSTRAINT ────────────────────────────────────────
            elif isinstance(action, exp.AddConstraint):
                findings.extend(self._check_add_constraint(stmt, action))

        return findings

    def _check_add_column(
        self, stmt: ParsedStatement, col_def: exp.ColumnDef
    ) -> Finding | None:
        """
        Flag ADD COLUMN col TYPE NOT NULL DEFAULT <value>.

        In sqlglot v30, ADD COLUMN actions are ColumnDef nodes directly in
        Alter.args["actions"].  Constraints live in ColumnDef.args["constraints"]
        as ColumnConstraint(kind=NotNullColumnConstraint|DefaultColumnConstraint|...).
        """
        constraints = col_def.args.get("constraints") or []
        has_not_null = any(
            isinstance(c.args.get("kind"), exp.NotNullColumnConstraint)
            for c in constraints
        )
        has_default = any(
            isinstance(c.args.get("kind"), exp.DefaultColumnConstraint)
            for c in constraints
        )

        if has_not_null and has_default:
            return Finding(
                rule_id=self.RULE_ID,
                severity="high",
                statement=stmt.raw_sql,
                line_number=stmt.line_number,
                explanation=(
                    "ADD COLUMN with NOT NULL and a non-null DEFAULT causes a full table rewrite "
                    "on PostgreSQL < 11, holding an ACCESS EXCLUSIVE lock for the entire duration. "
                    "On PG 11+ this is metadata-only for constant defaults, but PG version cannot "
                    "be determined from static analysis alone — treat as high risk."
                ),
                suggested_fix=(
                    "Safe pattern: (1) ADD COLUMN col TYPE DEFAULT NULL (nullable, fast). "
                    "(2) Backfill: UPDATE table SET col = <value> WHERE col IS NULL; in batches. "
                    "(3) ALTER COLUMN col SET NOT NULL; (4) ALTER COLUMN col SET DEFAULT <value>; "
                    "Each step takes a brief lock. Alternatively, confirm you are running PG 11+ "
                    "and the default is a constant expression, then suppress this finding."
                ),
            )
        return None

    def _check_add_constraint(
        self, stmt: ParsedStatement, action: exp.AddConstraint
    ) -> list[Finding]:
        """
        In sqlglot v30, AddConstraint.args["expressions"] is a list of
        Constraint(this=<name_identifier>, expressions=[ForeignKey|PrimaryKey|...]).

        NOT VALID is on the root Alter node (stmt.ast.args["not_valid"]).
        """
        findings: list[Finding] = []
        not_valid = bool(stmt.ast.args.get("not_valid"))

        for constraint_wrapper in (action.args.get("expressions") or []):
            # Each item is a Constraint node wrapping the actual constraint type
            inner_exprs = (
                constraint_wrapper.args.get("expressions")
                if hasattr(constraint_wrapper, "args")
                else []
            ) or []

            for inner in inner_exprs:
                # ── PRIMARY KEY ───────────────────────────────────────
                if isinstance(inner, exp.PrimaryKey):
                    findings.append(
                        Finding(
                            rule_id=self.RULE_ID,
                            severity="high",
                            statement=stmt.raw_sql,
                            line_number=stmt.line_number,
                            explanation=(
                                "ADD PRIMARY KEY rebuilds the primary index under an ACCESS EXCLUSIVE "
                                "lock. On large tables this can take significant time, blocking all "
                                "reads and writes."
                            ),
                            suggested_fix=(
                                "Create the index first with `CREATE UNIQUE INDEX CONCURRENTLY pk_idx ON "
                                "table (col);` (no lock), then attach it: `ALTER TABLE table ADD CONSTRAINT "
                                "pk_name PRIMARY KEY USING INDEX pk_idx;` (brief lock)."
                            ),
                        )
                    )

                # ── FOREIGN KEY ───────────────────────────────────────
                elif isinstance(inner, exp.ForeignKey):
                    if not not_valid:
                        findings.append(
                            Finding(
                                rule_id=self.RULE_ID,
                                severity="high",
                                statement=stmt.raw_sql,
                                line_number=stmt.line_number,
                                explanation=(
                                    "ADD CONSTRAINT FOREIGN KEY without NOT VALID scans the entire table "
                                    "to validate existing rows, holding an ACCESS EXCLUSIVE lock for the "
                                    "full scan duration."
                                ),
                                suggested_fix=(
                                    "Use two steps: (1) ADD CONSTRAINT fk FOREIGN KEY … NOT VALID; "
                                    "(2) VALIDATE CONSTRAINT fk; (uses ShareUpdateExclusiveLock — "
                                    "does NOT block reads/writes). This splits the lock from the scan."
                                ),
                            )
                        )

                # ── CHECK CONSTRAINT ──────────────────────────────────
                elif isinstance(inner, exp.CheckColumnConstraint):
                    if not not_valid:
                        findings.append(
                            Finding(
                                rule_id=self.RULE_ID,
                                severity="high",
                                statement=stmt.raw_sql,
                                line_number=stmt.line_number,
                                explanation=(
                                    "ADD CONSTRAINT CHECK without NOT VALID validates all existing rows "
                                    "under an ACCESS EXCLUSIVE lock."
                                ),
                                suggested_fix=(
                                    "Use NOT VALID on the ADD CONSTRAINT step, then run "
                                    "VALIDATE CONSTRAINT separately (takes ShareUpdateExclusiveLock, "
                                    "does not block reads)."
                                ),
                            )
                        )

        return findings
