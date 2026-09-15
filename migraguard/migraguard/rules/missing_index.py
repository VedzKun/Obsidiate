"""
migraguard.rules.missing_index
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Rule MG002 — Missing Index on Foreign Key Column.

PostgreSQL does NOT automatically create an index when you add a FOREIGN KEY
constraint (unlike MySQL).

sqlglot v30 AST notes:
  - ADD CONSTRAINT FK → AddConstraint.expressions = [Constraint(expressions=[ForeignKey(expressions=[col,...], reference=...)])]
  - Inline REFERENCES → ColumnDef.constraints = [ColumnConstraint(kind=Reference(...))]
  - FK columns list: ForeignKey.args["expressions"] → [Column(...)]
  - CREATE INDEX → Create(kind="INDEX", this=Index(table=Table(...), params=IndexParameters(columns=[Ordered(this=Column(...))])))
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlglot import exp

from migraguard.parser import MigrationContext, ParsedStatement, StatementType
from migraguard.rules.base import BaseRule, Finding


@dataclass
class _FkRef:
    """Tracks a single foreign key relationship found in the migration."""
    table: str
    column: str
    line_number: int
    raw_sql: str


class MissingIndexRule(BaseRule):
    """Detect foreign key columns added without a corresponding index."""

    RULE_ID = "MG002"
    DESCRIPTION = (
        "Detects new foreign key columns that have no corresponding index "
        "in the same migration."
    )

    def check(
        self,
        statements: list[ParsedStatement],
        context: MigrationContext,
    ) -> list[Finding]:
        fk_refs = self._collect_fk_refs(statements)
        if not fk_refs:
            return []

        # Use the parser-populated index map, supplemented by inline scan
        indexed = dict(context.created_indexes)
        inline = self._collect_inline_indexes(statements)
        for tbl, cols in inline.items():
            indexed.setdefault(tbl, set()).update(cols)

        findings: list[Finding] = []
        for fk in fk_refs:
            if fk.column not in indexed.get(fk.table, set()):
                findings.append(
                    Finding(
                        rule_id=self.RULE_ID,
                        severity="medium",
                        statement=fk.raw_sql,
                        line_number=fk.line_number,
                        explanation=(
                            f"Column `{fk.table}.{fk.column}` is a foreign key but has no "
                            f"index defined in this migration. PostgreSQL does not create FK "
                            f"indexes automatically. Without an index, joins and cascade deletes "
                            f"on this column will trigger full sequential scans."
                        ),
                        suggested_fix=(
                            f"Add the following statement to this migration:\n"
                            f"  CREATE INDEX CONCURRENTLY idx_{fk.table}_{fk.column} "
                            f"ON {fk.table} ({fk.column});\n"
                            f"Using CONCURRENTLY avoids a table lock during index build."
                        ),
                    )
                )
        return findings

    # ------------------------------------------------------------------
    # FK collection
    # ------------------------------------------------------------------

    def _collect_fk_refs(self, statements: list[ParsedStatement]) -> list[_FkRef]:
        refs: list[_FkRef] = []
        for stmt in statements:
            if stmt.statement_type != StatementType.ALTER_TABLE:
                continue

            tbl_node = stmt.ast.args.get("this")
            if tbl_node is None:
                continue
            table_name = (
                tbl_node.name.lower() if hasattr(tbl_node, "name") else str(tbl_node).lower()
            )

            for action in (stmt.ast.args.get("actions") or []):
                if isinstance(action, exp.AddConstraint):
                    refs.extend(self._refs_from_add_constraint(action, table_name, stmt))
                elif isinstance(action, exp.ColumnDef):
                    ref = self._ref_from_column_def(action, table_name, stmt)
                    if ref:
                        refs.append(ref)

        return refs

    def _refs_from_add_constraint(
        self,
        action: exp.AddConstraint,
        table_name: str,
        stmt: ParsedStatement,
    ) -> list[_FkRef]:
        """
        In v30: AddConstraint.expressions = [Constraint(this=name, expressions=[ForeignKey(...)])]
        ForeignKey.args["expressions"] = [Column(this=Identifier(this=col_name))]
        """
        refs: list[_FkRef] = []
        for constraint_wrapper in (action.args.get("expressions") or []):
            inner_exprs = (
                constraint_wrapper.args.get("expressions")
                if hasattr(constraint_wrapper, "args") else []
            ) or []
            for inner in inner_exprs:
                if not isinstance(inner, exp.ForeignKey):
                    continue
                fk_cols = inner.args.get("expressions") or []
                for col_node in fk_cols:
                    col_name = (
                        col_node.name.lower()
                        if hasattr(col_node, "name")
                        else str(col_node).lower()
                    )
                    refs.append(_FkRef(
                        table=table_name,
                        column=col_name,
                        line_number=stmt.line_number,
                        raw_sql=stmt.raw_sql,
                    ))
        return refs

    def _ref_from_column_def(
        self,
        col_def: exp.ColumnDef,
        table_name: str,
        stmt: ParsedStatement,
    ) -> _FkRef | None:
        """
        Check if the ColumnDef has an inline REFERENCES constraint.
        In v30: ColumnDef.constraints = [ColumnConstraint(kind=Reference(...))]
        """
        col_name = col_def.args.get("this")
        if col_name is None:
            return None
        col_name_str = col_name.name.lower() if hasattr(col_name, "name") else str(col_name).lower()

        for constraint in (col_def.args.get("constraints") or []):
            kind = constraint.args.get("kind")
            if isinstance(kind, exp.Reference):
                return _FkRef(
                    table=table_name,
                    column=col_name_str,
                    line_number=stmt.line_number,
                    raw_sql=stmt.raw_sql,
                )
        return None

    # ------------------------------------------------------------------
    # Inline index collection
    # ------------------------------------------------------------------

    def _collect_inline_indexes(
        self, statements: list[ParsedStatement]
    ) -> dict[str, set[str]]:
        """
        Supplement the parser's index map by scanning CREATE INDEX statements.
        Handles v30 shape: Create(kind="INDEX", this=Index(table=Table(...), params=IndexParameters(columns=[Ordered(this=Column(...))])))
        """
        result: dict[str, set[str]] = {}
        for stmt in statements:
            if stmt.statement_type != StatementType.CREATE_INDEX:
                continue
            node = stmt.ast
            index_expr = node.args.get("this")
            if not index_expr:
                continue
            # Table is at Index.args["table"]
            tbl_node = index_expr.args.get("table")
            if not tbl_node:
                continue
            tbl = tbl_node.name.lower() if hasattr(tbl_node, "name") else str(tbl_node).lower()
            params = index_expr.args.get("params")
            if not params:
                continue
            cols = params.args.get("columns") or []
            if not cols:
                continue
            first = cols[0]
            actual = first.args.get("this") if hasattr(first, "args") else first
            col = actual.name.lower() if hasattr(actual, "name") else str(actual).lower()
            result.setdefault(tbl, set()).add(col)
        return result
