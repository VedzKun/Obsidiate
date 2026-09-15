"""
migraguard.parser
~~~~~~~~~~~~~~~~~

Parses a raw .sql migration file into a list of :class:`ParsedStatement`
objects and a :class:`MigrationContext` that rules can query for
cross-statement information (e.g. "were any indexes created in this file?").

Uses ``sqlglot`` (v30+) with the ``postgres`` dialect — no hand-rolled SQL parsing.

sqlglot v30 node shapes (relevant to MigraGuard):
  - ALTER TABLE → exp.Alter  (kind="TABLE" in node.args["kind"])
  - DROP TABLE  → exp.Drop   (kind="TABLE", tables=[...])
  - CREATE TABLE → exp.Create (kind="TABLE")
  - CREATE INDEX  → exp.Create (kind="INDEX", this=Index(table=..., params=...))
  - ADD COLUMN action  → exp.ColumnDef  (in Alter.args["actions"])
  - ALTER COLUMN action → exp.AlterColumn
  - ADD CONSTRAINT action → exp.AddConstraint
  - DROP COLUMN action → exp.Drop (kind="COLUMN", tables=[Column(...)])
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional

import sqlglot
from sqlglot import exp


# ---------------------------------------------------------------------------
# Statement type classification
# ---------------------------------------------------------------------------

class StatementType(Enum):
    ALTER_TABLE = auto()
    CREATE_TABLE = auto()
    DROP_TABLE = auto()
    CREATE_INDEX = auto()
    DROP_INDEX = auto()
    INSERT = auto()
    UPDATE = auto()
    DELETE = auto()
    OTHER = auto()


def _classify(node: exp.Expression) -> StatementType:
    """Map a sqlglot v30 AST node to a :class:`StatementType`."""
    if isinstance(node, exp.Alter):
        kind = (node.args.get("kind") or "").upper()
        if kind == "TABLE":
            return StatementType.ALTER_TABLE
        return StatementType.OTHER

    if isinstance(node, exp.Drop):
        kind = (node.args.get("kind") or "").upper()
        if kind == "TABLE":
            return StatementType.DROP_TABLE
        if kind == "INDEX":
            return StatementType.DROP_INDEX
        return StatementType.OTHER

    if isinstance(node, exp.Create):
        kind = (node.args.get("kind") or "").upper()
        if kind == "TABLE":
            return StatementType.CREATE_TABLE
        if kind == "INDEX":
            return StatementType.CREATE_INDEX
        return StatementType.OTHER

    if isinstance(node, exp.Insert):
        return StatementType.INSERT
    if isinstance(node, exp.Update):
        return StatementType.UPDATE
    if isinstance(node, exp.Delete):
        return StatementType.DELETE
    return StatementType.OTHER


# ---------------------------------------------------------------------------
# Core data structures
# ---------------------------------------------------------------------------

@dataclass
class ParsedStatement:
    """A single SQL statement with its AST and metadata."""

    ast: exp.Expression
    statement_type: StatementType
    raw_sql: str
    line_number: int  # 1-based, approximate start line


@dataclass
class MigrationContext:
    """
    Aggregated information about the entire migration file.

    Rules use this for cross-statement reasoning (e.g. MissingIndexRule
    checks whether a newly added FK column has a corresponding index created
    anywhere in the same file).
    """

    file_path: Path
    raw_content: str

    # Populated during parse
    statements: list[ParsedStatement] = field(default_factory=list)

    # Table names touched (lowercased) by any ALTER TABLE or CREATE TABLE
    touched_tables: set[str] = field(default_factory=set)

    # Indexes explicitly created in this migration.
    # Maps  table_name (lower) -> set of leading column names (lower).
    created_indexes: dict[str, set[str]] = field(default_factory=dict)

    # Whether a "down" section was detected in this file or as a sibling file.
    has_down_migration: bool = False

    # Raw text of the down-migration section (if detected inline).
    down_section_raw: Optional[str] = None


# ---------------------------------------------------------------------------
# Down-migration detection helpers
# ---------------------------------------------------------------------------

_DOWN_COMMENT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"--\s*down\b", re.IGNORECASE),
    re.compile(r"--\s*\+migrate\s+down\b", re.IGNORECASE),
    re.compile(r"--\s*!down\b", re.IGNORECASE),
    re.compile(r"--\s*@?down\b", re.IGNORECASE),
]

_DOWN_FILE_PATTERNS: list[str] = ["down", "rollback", "revert"]


def _detect_down_migration(file_path: Path, raw_content: str) -> tuple[bool, Optional[str]]:
    """Check whether this migration has a corresponding rollback definition."""
    for pattern in _DOWN_COMMENT_PATTERNS:
        match = pattern.search(raw_content)
        if match:
            return True, raw_content[match.start():]

    # Sibling file check (only for real paths)
    if file_path.exists() and file_path.parent != file_path:
        parent = file_path.parent
        stem = file_path.stem.lower()
        try:
            for sibling in parent.iterdir():
                if sibling == file_path:
                    continue
                sibling_name = sibling.name.lower()
                if any(kw in sibling_name for kw in _DOWN_FILE_PATTERNS):
                    numeric_prefix = re.match(r"^(\d+)", stem)
                    if numeric_prefix and numeric_prefix.group(1) in sibling_name:
                        return True, None
                    if stem in sibling_name or sibling_name.replace("down", "").strip("_-") in stem:
                        return True, None
        except OSError:
            pass

    return False, None


# ---------------------------------------------------------------------------
# Index extraction helpers (sqlglot v30)
# ---------------------------------------------------------------------------

def _extract_created_index(node: exp.Expression) -> Optional[tuple[str, str]]:
    """
    If *node* is a ``CREATE INDEX`` statement, return ``(table_name, leading_col)``
    for the first column in the index.  Returns ``None`` otherwise.

    sqlglot v30 shape:
      Create(kind="INDEX", this=Index(table=Table(...), params=IndexParameters(columns=[Ordered(...)])))
    """
    if not isinstance(node, exp.Create):
        return None
    if (node.args.get("kind") or "").upper() != "INDEX":
        return None

    index_expr = node.args.get("this")  # Index node
    if not index_expr:
        return None

    # Table: Index.args["table"] → Table node
    tbl_node = index_expr.args.get("table")
    if not tbl_node:
        return None
    table_name = tbl_node.name.lower() if hasattr(tbl_node, "name") else str(tbl_node).lower()

    # Columns: IndexParameters.args["columns"] → [Ordered(this=Column(...))]
    params = index_expr.args.get("params")
    if not params:
        return None
    columns = params.args.get("columns") or []
    if not columns:
        return None

    first_col = columns[0]
    # Ordered wraps the Column; Column has .name
    actual_col = first_col.args.get("this") if hasattr(first_col, "args") else first_col
    col_name = (
        actual_col.name.lower()
        if hasattr(actual_col, "name")
        else str(actual_col).lower()
    )
    return table_name, col_name


def _extract_table_name_from_alter(node: exp.Alter) -> str:
    """Extract the lowercased table name from an ALTER TABLE node."""
    tbl_node = node.args.get("this")
    if tbl_node is None:
        return ""
    return tbl_node.name.lower() if hasattr(tbl_node, "name") else str(tbl_node).lower()


# ---------------------------------------------------------------------------
# Line-number approximation
# ---------------------------------------------------------------------------

def _approx_line_number(raw_sql: str, full_raw: str, search_start: int = 0) -> int:
    """Approximate 1-based line number where ``raw_sql`` starts in ``full_raw``."""
    stripped = raw_sql.strip()
    if not stripped:
        return 1
    search_for = stripped[:min(40, len(stripped))]
    idx = full_raw.find(search_for, search_start)
    if idx == -1:
        idx = search_start
    return full_raw[:idx].count("\n") + 1


# ---------------------------------------------------------------------------
# Context population helpers
# ---------------------------------------------------------------------------

def _populate_context(ctx: MigrationContext, node: exp.Expression, stmt_type: StatementType) -> None:
    """Update ctx with metadata extracted from one parsed statement node."""

    # Touched tables (ALTER TABLE / CREATE TABLE)
    if stmt_type in (StatementType.ALTER_TABLE, StatementType.CREATE_TABLE):
        tbl_node = node.args.get("this")
        if tbl_node is not None:
            tbl_name = (
                tbl_node.name.lower()
                if hasattr(tbl_node, "name")
                else str(tbl_node).lower()
            )
            ctx.touched_tables.add(tbl_name)

        # Implicit indexes from ADD PRIMARY KEY inside ALTER TABLE
        if stmt_type == StatementType.ALTER_TABLE:
            tbl_name_str = _extract_table_name_from_alter(node)  # type: ignore[arg-type]
            for action in (node.args.get("actions") or []):
                if isinstance(action, exp.AddConstraint):
                    for constraint_wrapper in (action.args.get("expressions") or []):
                        # In v30: AddConstraint.expressions = [Constraint(this=name, expressions=[PrimaryKey(...)])]
                        inner_exprs = constraint_wrapper.args.get("expressions") if hasattr(constraint_wrapper, "args") else []
                        for inner in (inner_exprs or []):
                            if isinstance(inner, exp.PrimaryKey):
                                pk_cols = inner.args.get("expressions") or []
                                for col_node in pk_cols:
                                    col_name = (
                                        col_node.name.lower()
                                        if hasattr(col_node, "name")
                                        else str(col_node).lower()
                                    )
                                    if tbl_name_str:
                                        ctx.created_indexes.setdefault(tbl_name_str, set()).add(col_name)

    # Created indexes (CREATE INDEX)
    index_info = _extract_created_index(node)
    if index_info:
        tbl, col = index_info
        ctx.created_indexes.setdefault(tbl, set()).add(col)


# ---------------------------------------------------------------------------
# Public parse API
# ---------------------------------------------------------------------------

def parse_file(file_path: Path) -> MigrationContext:
    """
    Parse a ``.sql`` migration file and return a :class:`MigrationContext`.

    Raises :class:`ValueError` if the file cannot be read or contains no
    parseable SQL.
    """
    file_path = Path(file_path)
    try:
        raw_content = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"Cannot read migration file {file_path}: {exc}") from exc

    ctx = MigrationContext(file_path=file_path, raw_content=raw_content)
    ctx.has_down_migration, ctx.down_section_raw = _detect_down_migration(file_path, raw_content)

    return _parse_content(raw_content, ctx)


def parse_sql(sql: str, source_label: str = "<inline>") -> MigrationContext:
    """Convenience wrapper for parsing a raw SQL string (useful in tests)."""
    tmp_path = Path(source_label)
    ctx = MigrationContext(file_path=tmp_path, raw_content=sql)
    ctx.has_down_migration, ctx.down_section_raw = _detect_down_migration(tmp_path, sql)
    return _parse_content(sql, ctx)


def _parse_content(sql: str, ctx: MigrationContext) -> MigrationContext:
    """Internal: parse SQL string and populate ctx.statements."""
    try:
        ast_nodes = sqlglot.parse(sql, read="postgres", error_level=sqlglot.ErrorLevel.WARN)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Failed to parse SQL: {exc}") from exc

    search_cursor = 0
    for node in ast_nodes:
        if node is None:
            continue

        raw_sql = node.sql(dialect="postgres")
        stmt_type = _classify(node)
        line_no = _approx_line_number(raw_sql, sql, search_cursor)

        stripped_head = raw_sql.strip()[:40]
        found_at = sql.find(stripped_head, search_cursor)
        if found_at != -1:
            search_cursor = found_at + len(stripped_head)

        parsed = ParsedStatement(
            ast=node,
            statement_type=stmt_type,
            raw_sql=raw_sql,
            line_number=line_no,
        )
        ctx.statements.append(parsed)
        _populate_context(ctx, node, stmt_type)

    return ctx
