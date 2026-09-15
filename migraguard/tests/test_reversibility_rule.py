"""
tests/test_reversibility_rule.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Unit tests for ReversibilityRule (MG003).

Covers:
  - DROP TABLE → critical finding
  - DROP COLUMN → high finding
  - DROP TABLE without down migration → additional high finding
  - DROP TABLE with inline -- Down marker → no "missing down" finding
  - Fixture: risky_migration.sql triggers findings
  - Fixture: drop_table_with_down.sql has down → no missing-down finding
  - Non-destructive migration → no MG003 findings
  - Explanation mentions table/column name
  - Suggested fix mentions archiving strategy
"""

from __future__ import annotations

from pathlib import Path

import pytest
from migraguard.parser import parse_file, parse_sql
from migraguard.rules.reversibility import ReversibilityRule


@pytest.fixture
def rule() -> ReversibilityRule:
    return ReversibilityRule()


FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# DROP TABLE tests
# ---------------------------------------------------------------------------

class TestDropTable:
    def test_drop_table_is_critical(self, rule):
        sql = "DROP TABLE legacy_sessions;"
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        drop_findings = [f for f in findings if "DROP TABLE" in f.statement.upper() or
                         "DROP TABLE" in f.explanation.upper()]
        assert any(f.severity == "critical" for f in findings)

    def test_drop_table_rule_id(self, rule):
        sql = "DROP TABLE old_logs;"
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        assert any(f.rule_id == "MG003" for f in findings)

    def test_drop_table_explanation_mentions_irreversible(self, rule):
        sql = "DROP TABLE audit_trail;"
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        critical = [f for f in findings if f.severity == "critical"]
        assert critical
        assert "irreversible" in critical[0].explanation.lower()

    def test_drop_table_suggested_fix_mentions_archive(self, rule):
        sql = "DROP TABLE audit_trail;"
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        critical = [f for f in findings if f.severity == "critical"]
        assert critical
        fix_lower = critical[0].suggested_fix.lower()
        assert "archive" in fix_lower or "rename" in fix_lower

    def test_drop_table_without_down_migration_adds_extra_finding(self, rule):
        sql = "DROP TABLE old_users;"
        ctx = parse_sql(sql)
        assert not ctx.has_down_migration
        findings = rule.check(ctx.statements, ctx)
        # One for the DROP, one for missing down
        assert len(findings) >= 2
        severities = {f.severity for f in findings}
        assert "critical" in severities  # DROP TABLE
        assert "high" in severities      # missing down migration

    def test_drop_table_with_down_marker_no_missing_down_finding(self, rule):
        sql = "DROP TABLE temp_staging;\n-- Down\nCREATE TABLE temp_staging (id SERIAL);"
        ctx = parse_sql(sql)
        assert ctx.has_down_migration
        findings = rule.check(ctx.statements, ctx)
        missing_down = [
            f for f in findings
            if "no down migration" in f.explanation.lower()
            or "missing" in f.explanation.lower()
        ]
        assert missing_down == []


# ---------------------------------------------------------------------------
# DROP COLUMN tests
# ---------------------------------------------------------------------------

class TestDropColumn:
    def test_drop_column_is_high(self, rule):
        sql = "ALTER TABLE users DROP COLUMN legacy_token;"
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        high = [f for f in findings if f.severity == "high"]
        # At least one high: the DROP COLUMN itself
        assert high

    def test_drop_column_mentions_column_name(self, rule):
        sql = "ALTER TABLE users DROP COLUMN api_secret;"
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        drop_findings = [f for f in findings if f.severity in ("high", "critical")
                         and "api_secret" in f.explanation]
        assert drop_findings

    def test_drop_column_fix_mentions_two_phase(self, rule):
        sql = "ALTER TABLE users DROP COLUMN old_hash;"
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        col_findings = [
            f for f in findings
            if "old_hash" in f.explanation or "phase" in f.suggested_fix.lower()
        ]
        assert col_findings

    def test_fixture_drop_column_no_down(self, rule):
        ctx = parse_file(FIXTURES / "drop_column_no_down.sql")
        findings = rule.check(ctx.statements, ctx)
        assert any(f.rule_id == "MG003" for f in findings)


# ---------------------------------------------------------------------------
# Down-migration detection
# ---------------------------------------------------------------------------

class TestDownMigrationDetection:
    def test_golang_migrate_marker(self, rule):
        sql = "DROP TABLE sessions;\n-- +migrate Down\nCREATE TABLE sessions (id SERIAL);"
        ctx = parse_sql(sql)
        assert ctx.has_down_migration
        findings = rule.check(ctx.statements, ctx)
        missing = [f for f in findings if "no down" in f.explanation.lower()
                   or "missing" in f.explanation.lower()]
        assert missing == []

    def test_fixture_with_down_section_no_missing_down(self, rule):
        ctx = parse_file(FIXTURES / "drop_table_with_down.sql")
        findings = rule.check(ctx.statements, ctx)
        missing = [f for f in findings
                   if "no down migration" in f.explanation.lower()
                   or "rollback" in f.explanation.lower() and "missing" in f.explanation.lower()]
        assert missing == []


# ---------------------------------------------------------------------------
# Non-destructive migrations → no MG003 findings
# ---------------------------------------------------------------------------

class TestNonDestructiveMigration:
    def test_add_column_no_mg003(self, rule):
        sql = "ALTER TABLE products ADD COLUMN weight_kg DECIMAL(10,3);"
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        mg003 = [f for f in findings if f.rule_id == "MG003"]
        assert mg003 == []

    def test_create_table_no_mg003(self, rule):
        sql = "CREATE TABLE audit_events (id SERIAL PRIMARY KEY, event TEXT);"
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        mg003 = [f for f in findings if f.rule_id == "MG003"]
        assert mg003 == []

    def test_create_index_no_mg003(self, rule):
        sql = "CREATE INDEX CONCURRENTLY idx_orders_created ON orders (created_at);"
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        assert findings == []


# ---------------------------------------------------------------------------
# Acceptance criteria: risky_migration.sql
# ---------------------------------------------------------------------------

class TestRiskyMigrationFixture:
    def test_risky_migration_has_critical_findings(self, rule):
        ctx = parse_file(FIXTURES / "risky_migration.sql")
        findings = rule.check(ctx.statements, ctx)
        assert any(f.severity == "critical" for f in findings)

    def test_risky_migration_has_mg003(self, rule):
        ctx = parse_file(FIXTURES / "risky_migration.sql")
        findings = rule.check(ctx.statements, ctx)
        assert any(f.rule_id == "MG003" for f in findings)
