import os
import json
from pathlib import Path

import pytest
import responses
from click.testing import CliRunner

from migraguard.cli import main
from migraguard.ci.github_client import GitHubClient


@pytest.fixture
def runner():
    return CliRunner()


@responses.activate
def test_ci_check_success_no_findings(runner, tmp_path):
    # Setup mock config
    config_file = tmp_path / ".migraguard.yml"
    config_file.write_text("migration_pattern: '**/*.sql'\nblocking_severities: ['critical']")
    
    # Setup mock SQL file with NO findings
    sql_file = tmp_path / "migrations" / "001_clean.sql"
    sql_file.parent.mkdir()
    sql_file.write_text("CREATE TABLE users (id INT PRIMARY KEY);")
    
    # Mock GitHub API
    os.environ["GITHUB_TOKEN"] = "fake-token"
    os.environ["GITHUB_API_URL"] = "https://api.github.com"
    
    # Mock PR files
    responses.add(
        responses.GET,
        "https://api.github.com/repos/org/repo/pulls/123/files?per_page=100&page=1",
        json=[{"filename": str(sql_file), "status": "added"}],
        match_querystring=True,
        status=200
    )
    responses.add(
        responses.GET,
        "https://api.github.com/repos/org/repo/pulls/123/files?per_page=100&page=2",
        json=[],
        match_querystring=True,
        status=200
    )
    
    # Mock post review
    responses.add(
        responses.POST,
        "https://api.github.com/repos/org/repo/pulls/123/reviews",
        json={},
        status=200
    )
    
    # Run CLI from the tmp_path so it picks up the config
    with runner.isolated_filesystem(temp_dir=tmp_path):
        os.chdir(tmp_path)
        result = runner.invoke(main, ["ci-check", "--pr", "123", "--repo", "org/repo", "--commit", "abc123sha"])
        
    assert result.exit_code == 0
    # Check that a review was posted with APPROVE
    assert len(responses.calls) == 3
    post_call = responses.calls[2]
    
    if isinstance(post_call.request.body, bytes):
        body_str = post_call.request.body.decode('utf-8')
    else:
        body_str = post_call.request.body
    post_data = json.loads(body_str)
    
    assert post_data["event"] == "APPROVE"
    assert "zero issues" in post_data["body"]
    assert len(post_data["comments"]) == 0


@responses.activate
def test_ci_check_failure_with_findings(runner, tmp_path):
    # Setup mock SQL file with a finding (e.g. missing index warning, or drop table)
    # Reversibility rule flags DROP TABLE
    sql_file = tmp_path / "migrations" / "002_bad.sql"
    sql_file.parent.mkdir(exist_ok=True)
    sql_file.write_text("DROP TABLE users;")
    
    os.environ["GITHUB_TOKEN"] = "fake-token"
    
    # Mock PR files
    responses.add(
        responses.GET,
        "https://api.github.com/repos/org/repo/pulls/123/files?per_page=100&page=1",
        json=[{"filename": str(sql_file), "status": "added"}],
        match_querystring=True,
        status=200
    )
    responses.add(
        responses.GET,
        "https://api.github.com/repos/org/repo/pulls/123/files?per_page=100&page=2",
        json=[],
        match_querystring=True,
        status=200
    )
    
    # Mock post review
    responses.add(
        responses.POST,
        "https://api.github.com/repos/org/repo/pulls/123/reviews",
        json={},
        status=200
    )
    
    with runner.isolated_filesystem(temp_dir=tmp_path):
        os.chdir(tmp_path)
        result = runner.invoke(main, ["ci-check", "--pr", "123", "--repo", "org/repo", "--commit", "abc123sha"])
        
    # Since DROP TABLE is CRITICAL and defaults block critical, it should exit 1
    assert result.exit_code == 1
    
    if result.exception and not isinstance(result.exception, SystemExit):
        print(f"Exception: {result.exception}")
        print(f"Output: {result.output}")
        raise result.exception
        
    # Check that a review was posted with REQUEST_CHANGES
    assert len(responses.calls) == 3, f"Expected 3 calls, got {len(responses.calls)}. Output: {result.output}"
    post_call = responses.calls[2]
    
    if isinstance(post_call.request.body, bytes):
        body_str = post_call.request.body.decode('utf-8')
    else:
        body_str = post_call.request.body
    post_data = json.loads(body_str)
    
    assert post_data["event"] == "REQUEST_CHANGES"
    assert len(post_data["comments"]) == 2
    assert any("DROP TABLE" in c["body"] for c in post_data["comments"])
