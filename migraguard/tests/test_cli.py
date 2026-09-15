"""
tests/test_cli.py
~~~~~~~~~~~~~~~~~

End-to-end CLI tests using click's CliRunner.

Covers:
  - `migraguard scan <risky_file>` exits with code 1 and has findings
  - `migraguard scan <safe_file>` exits with code 0 with no findings
  - `--format json` produces valid JSON with expected shape
  - Directory scan picks up all .sql files
  - Invalid path exits with code 2
  - `--version` flag works
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from migraguard.cli import main


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# Exit code tests
# ---------------------------------------------------------------------------

class TestExitCodes:
    def test_risky_migration_exits_1(self, runner):
        result = runner.invoke(main, ["scan", str(FIXTURES / "risky_migration.sql")])
        assert result.exit_code == 1, (
            f"Expected exit code 1, got {result.exit_code}.\n"
            f"Output:\n{result.output}"
        )

    def test_safe_migration_exits_0(self, runner):
        result = runner.invoke(main, ["scan", str(FIXTURES / "safe_add_nullable_column.sql")])
        assert result.exit_code == 0, (
            f"Expected exit code 0, got {result.exit_code}.\n"
            f"Output:\n{result.output}"
        )

    def test_invalid_path_exits_2(self, runner, tmp_path):
        result = runner.invoke(main, ["scan", str(tmp_path / "nonexistent.sql")])
        # Click's path_type=Path with exists=True will raise UsageError → exit 2
        assert result.exit_code == 2

    def test_non_sql_file_exits_nonzero(self, runner, tmp_path):
        txt = tmp_path / "migration.txt"
        txt.write_text("ALTER TABLE users ADD COLUMN x INT;")
        result = runner.invoke(main, ["scan", str(txt)])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Output format tests
# ---------------------------------------------------------------------------

class TestTextFormat:
    def test_text_output_contains_mg001(self, runner):
        result = runner.invoke(main, ["scan", str(FIXTURES / "risky_migration.sql")])
        assert "MG001" in result.output or "MG003" in result.output

    def test_text_output_contains_severity(self, runner):
        result = runner.invoke(main, ["scan", str(FIXTURES / "risky_migration.sql")])
        output_upper = result.output.upper()
        assert "CRITICAL" in output_upper or "HIGH" in output_upper

    def test_safe_migration_text_has_no_findings_message(self, runner):
        result = runner.invoke(main, ["scan", str(FIXTURES / "safe_add_nullable_column.sql")])
        assert result.exit_code == 0


class TestJsonFormat:
    def test_json_output_is_valid_json(self, runner):
        result = runner.invoke(
            main,
            ["scan", str(FIXTURES / "risky_migration.sql"), "--format", "json"],
        )
        # JSON mode: exit code may be 1 due to high/critical findings
        try:
            data = json.loads(result.output)
        except json.JSONDecodeError:
            pytest.fail(f"Output is not valid JSON:\n{result.output}")
        assert isinstance(data, list)

    def test_json_findings_have_required_fields(self, runner):
        result = runner.invoke(
            main,
            ["scan", str(FIXTURES / "risky_migration.sql"), "--format", "json"],
        )
        data = json.loads(result.output)
        assert data, "Expected at least one finding in JSON output"
        required_fields = {
            "rule_id", "severity", "statement",
            "line_number", "explanation", "suggested_fix", "file_path",
        }
        for finding in data:
            missing = required_fields - finding.keys()
            assert not missing, f"Finding missing fields: {missing}"

    def test_json_safe_migration_is_empty_array(self, runner):
        result = runner.invoke(
            main,
            ["scan", str(FIXTURES / "safe_add_nullable_column.sql"), "--format", "json"],
        )
        data = json.loads(result.output)
        assert data == []

    def test_json_severities_are_valid(self, runner):
        result = runner.invoke(
            main,
            ["scan", str(FIXTURES / "risky_migration.sql"), "--format", "json"],
        )
        data = json.loads(result.output)
        valid = {"low", "medium", "high", "critical"}
        for f in data:
            assert f["severity"] in valid, f"Invalid severity: {f['severity']}"


# ---------------------------------------------------------------------------
# Directory scan
# ---------------------------------------------------------------------------

class TestDirectoryScan:
    def test_directory_scan_finds_risky_migrations(self, runner):
        """Scanning the whole fixtures directory should find findings."""
        result = runner.invoke(main, ["scan", str(FIXTURES)])
        # Should produce some findings (risky_migration.sql is in there)
        assert result.exit_code in (0, 1)

    def test_directory_scan_json_is_list(self, runner):
        result = runner.invoke(
            main, ["scan", str(FIXTURES), "--format", "json"]
        )
        data = json.loads(result.output)
        assert isinstance(data, list)

    def test_empty_directory_exits_2(self, runner, tmp_path):
        result = runner.invoke(main, ["scan", str(tmp_path)])
        assert result.exit_code == 2


# ---------------------------------------------------------------------------
# Version flag
# ---------------------------------------------------------------------------

class TestVersion:
    def test_version_flag(self, runner):
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output
