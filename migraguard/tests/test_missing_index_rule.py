"""
tests/test_missing_index_rule.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Unit tests for MissingIndexRule (MG002).

Covers:
  - Explicit ADD CONSTRAINT FK with no index → medium finding
  - Inline REFERENCES syntax with no index → medium finding
  - FK with CREATE INDEX CONCURRENTLY in same migration → no finding
  - No FK at all → no finding
  - Multiple FKs, only one indexed → one finding
  - Suggested fix contains CONCURRENTLY
"""

from __future__ import annotations

from pathlib import Path

import pytest
from migraguard.parser import parse_file, parse_sql
from migraguard.rules.missing_index import MissingIndexRule


@pytest.fixture
def rule() -> MissingIndexRule:
    return MissingIndexRule()


FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Triggering cases
# ---------------------------------------------------------------------------

class TestExplicitFkNoIndex:
    def test_explicit_fk_no_index_emits_medium(self, rule):
        sql = """
        ALTER TABLE order_items ADD COLUMN user_id INT;
        ALTER TABLE order_items
            ADD CONSTRAINT fk_oi_user FOREIGN KEY (user_id) REFERENCES users(id);
        """
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        assert len(findings) == 1
        assert findings[0].severity == "medium"
        assert findings[0].rule_id == "MG002"

    def test_finding_mentions_table_and_column(self, rule):
        sql = """
        ALTER TABLE payments ADD COLUMN customer_id INT;
        ALTER TABLE payments
            ADD CONSTRAINT fk_payments_customer FOREIGN KEY (customer_id) REFERENCES customers(id);
        """
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        assert findings
        assert "payments" in findings[0].explanation
        assert "customer_id" in findings[0].explanation

    def test_suggested_fix_contains_concurrently(self, rule):
        sql = """
        ALTER TABLE payments ADD COLUMN customer_id INT;
        ALTER TABLE payments
            ADD CONSTRAINT fk_payments_customer FOREIGN KEY (customer_id) REFERENCES customers(id);
        """
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        assert "CONCURRENTLY" in findings[0].suggested_fix

    def test_fixture_fk_no_index(self, rule):
        ctx = parse_file(FIXTURES / "missing_index_fk.sql")
        findings = rule.check(ctx.statements, ctx)
        assert len(findings) >= 1
        assert all(f.severity == "medium" for f in findings)


class TestInlineReferencesNoIndex:
    def test_inline_references_no_index_emits_finding(self, rule):
        sql = "ALTER TABLE comments ADD COLUMN post_id INT REFERENCES posts(id);"
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        assert len(findings) == 1
        assert findings[0].rule_id == "MG002"

    def test_fixture_inline_ref(self, rule):
        ctx = parse_file(FIXTURES / "missing_index_inline_ref.sql")
        findings = rule.check(ctx.statements, ctx)
        assert len(findings) >= 1


# ---------------------------------------------------------------------------
# Safe / non-triggering cases
# ---------------------------------------------------------------------------

class TestFkWithIndexInSameMigration:
    def test_create_index_concurrently_suppresses_finding(self, rule):
        sql = """
        ALTER TABLE order_items ADD COLUMN user_id INT;
        CREATE INDEX CONCURRENTLY idx_order_items_user_id ON order_items (user_id);
        ALTER TABLE order_items
            ADD CONSTRAINT fk_oi_user FOREIGN KEY (user_id) REFERENCES users(id) NOT VALID;
        """
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        mg002 = [f for f in findings if f.rule_id == "MG002"]
        assert mg002 == [], f"Expected no MG002 findings, got: {mg002}"

    def test_fixture_safe_indexed_fk(self, rule):
        ctx = parse_file(FIXTURES / "safe_indexed_fk.sql")
        findings = rule.check(ctx.statements, ctx)
        mg002 = [f for f in findings if f.rule_id == "MG002"]
        assert mg002 == []


class TestNoFkNoFinding:
    def test_plain_add_column_no_finding(self, rule):
        sql = "ALTER TABLE users ADD COLUMN first_name VARCHAR(100);"
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        assert findings == []

    def test_create_table_only_no_finding(self, rule):
        sql = """
        CREATE TABLE products (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL
        );
        """
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        assert findings == []


class TestMultipleFks:
    def test_two_fks_one_indexed_emits_one_finding(self, rule):
        sql = """
        ALTER TABLE line_items ADD COLUMN order_id INT;
        ALTER TABLE line_items ADD COLUMN product_id INT;
        CREATE INDEX CONCURRENTLY idx_li_order ON line_items (order_id);
        ALTER TABLE line_items
            ADD CONSTRAINT fk_li_order FOREIGN KEY (order_id) REFERENCES orders(id) NOT VALID;
        ALTER TABLE line_items
            ADD CONSTRAINT fk_li_product FOREIGN KEY (product_id) REFERENCES products(id) NOT VALID;
        """
        ctx = parse_sql(sql)
        findings = rule.check(ctx.statements, ctx)
        mg002 = [f for f in findings if f.rule_id == "MG002"]
        # Only product_id is unindexed
        assert len(mg002) == 1
        assert "product_id" in mg002[0].explanation
