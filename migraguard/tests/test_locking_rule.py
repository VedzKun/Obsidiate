"""
tests/test_locking_rule.py
~~~~~~~~~~~~~~~~~~~~~~~~~~

Unit tests for LockingOperationRule (MG001).

Covers:
  - ALTER COLUMN type change → critical
  - ADD COLUMN NOT NULL DEFAULT → high
  - ADD CONSTRAINT FK without NOT VALID → high
  - ADD CONSTRAINT FK WITH NOT VALID → no finding (safe)
  - ADD COLUMN nullable no default → no finding (safe)
  - ADD PRIMARY KEY → high
"""

from __future__ import annotations

import pytest
from migraguard.parser import parse_sql
from migraguard.rules.locking import LockingOperationRule


@pytest.fixture
def rule() -> LockingOperationRule:
    return LockingOperationRule()


# ---------------------------------------------------------------------------
# Triggering cases
# ---------------------------------------------------------------------------

class TestAlterColumnTypeChange:
    def test_basic_type_change_is_critical(self, rule):
        sql = "ALTER TABLE orders ALTER COLUMN total TYPE NUMERIC(12,4);"
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        assert len(findings) == 1
        assert findings[0].severity == "critical"
        assert findings[0].rule_id == "MG001"

    def test_type_change_explanation_mentions_rewrite(self, rule):
        sql = "ALTER TABLE orders ALTER COLUMN total TYPE NUMERIC(12,4);"
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        assert "rewrite" in findings[0].explanation.lower()

    def test_type_change_suggested_fix_mentions_backfill(self, rule):
        sql = "ALTER TABLE orders ALTER COLUMN total TYPE NUMERIC(12,4);"
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        assert "backfill" in findings[0].suggested_fix.lower()

    def test_fixture_file_type_change(self, rule, tmp_path):
        """Ensure the fixture file triggers a critical finding."""
        from pathlib import Path
        fixture = Path(__file__).parent / "fixtures" / "locking_type_change.sql"
        from migraguard.parser import parse_file
        ctx = parse_file(fixture)
        findings = rule.check(ctx.statements, ctx)
        assert any(f.severity == "critical" for f in findings)


class TestAddColumnNotNull:
    def test_not_null_with_default_is_high(self, rule):
        sql = "ALTER TABLE users ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'active';"
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        assert len(findings) == 1
        assert findings[0].severity == "high"

    def test_nullable_column_no_finding(self, rule):
        """Nullable ADD COLUMN must not trigger MG001."""
        sql = "ALTER TABLE users ADD COLUMN middle_name VARCHAR(100);"
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        assert findings == []

    def test_not_null_without_default_no_finding(self, rule):
        """NOT NULL without a DEFAULT is a metadata-only op (at CREATE time it's fine)."""
        sql = "ALTER TABLE users ADD COLUMN code VARCHAR(10) NOT NULL;"
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        # No DEFAULT means it's only dangerous at insert time, not a table lock issue
        assert findings == []

    def test_fixture_file_add_column_not_null(self, rule):
        from pathlib import Path
        from migraguard.parser import parse_file
        fixture = Path(__file__).parent / "fixtures" / "locking_add_column_not_null.sql"
        ctx = parse_file(fixture)
        findings = rule.check(ctx.statements, ctx)
        assert any(f.severity == "high" for f in findings)


class TestAddConstraintForeignKey:
    def test_fk_without_not_valid_is_high(self, rule):
        sql = """
        ALTER TABLE order_items
            ADD CONSTRAINT fk_oi_product
            FOREIGN KEY (product_id) REFERENCES products(id);
        """
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        assert any(f.rule_id == "MG001" and f.severity == "high" for f in findings)

    def test_fk_with_not_valid_no_finding(self, rule):
        sql = """
        ALTER TABLE order_items
            ADD CONSTRAINT fk_oi_product
            FOREIGN KEY (product_id) REFERENCES products(id) NOT VALID;
        """
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        mg001 = [f for f in findings if f.rule_id == "MG001"]
        # NOT VALID should suppress the locking finding for this FK
        assert not any("FOREIGN KEY" in f.explanation or "foreign key" in f.explanation.lower() for f in mg001
                       if "NOT VALID" not in f.explanation and "not valid" not in f.explanation.lower())

    def test_fk_fix_mentions_not_valid(self, rule):
        sql = """
        ALTER TABLE order_items
            ADD CONSTRAINT fk_oi_product
            FOREIGN KEY (product_id) REFERENCES products(id);
        """
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        assert findings
        assert "NOT VALID" in findings[0].suggested_fix or "not valid" in findings[0].suggested_fix.lower()

    def test_fixture_fk_no_not_valid(self, rule):
        from pathlib import Path
        from migraguard.parser import parse_file
        fixture = Path(__file__).parent / "fixtures" / "locking_fk_no_not_valid.sql"
        ctx = parse_file(fixture)
        findings = rule.check(ctx.statements, ctx)
        assert len(findings) >= 1
        assert any(f.severity == "high" for f in findings)


class TestAddPrimaryKey:
    def test_add_primary_key_is_high(self, rule):
        sql = "ALTER TABLE products ADD CONSTRAINT products_pkey PRIMARY KEY (id);"
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        assert any(f.severity == "high" and f.rule_id == "MG001" for f in findings)

    def test_primary_key_fix_mentions_concurrently(self, rule):
        sql = "ALTER TABLE products ADD CONSTRAINT products_pkey PRIMARY KEY (id);"
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        assert findings
        assert "CONCURRENTLY" in findings[0].suggested_fix


class TestMultipleActionsInSingleAlter:
    def test_two_risky_actions_produce_two_findings(self, rule):
        sql = """
        ALTER TABLE events ALTER COLUMN payload TYPE JSONB;
        ALTER TABLE events ADD COLUMN status VARCHAR(20) NOT NULL DEFAULT 'pending';
        """
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        assert len(findings) == 2

    def test_mixed_safe_and_risky(self, rule):
        sql = """
        ALTER TABLE events ADD COLUMN notes TEXT;
        ALTER TABLE events ALTER COLUMN payload TYPE JSONB;
        """
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        # Only the type change should fire
        assert len(findings) == 1
        assert findings[0].severity == "critical"
