from __future__ import annotations

import os
from typing import Any

import requests


class GitHubClient:
    def __init__(self, token: str | None = None) -> None:
        self.token = token or os.environ.get("GITHUB_TOKEN")
        if not self.token:
            raise ValueError("GitHub token is required (pass directly or set GITHUB_TOKEN env var).")
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.v3+json",
        })
        self.api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com")

    def get_pr_changed_files(self, repo: str, pr_number: int) -> list[str]:
        """Fetch the list of changed files in a PR (added or modified)."""
        url = f"{self.api_url}/repos/{repo}/pulls/{pr_number}/files"
        files = []
        page = 1
        while True:
            response = self.session.get(url, params={"per_page": 100, "page": page})
            response.raise_for_status()
            data = response.json()
            if not data:
                break
            for item in data:
                # We only care about added or modified files (not removed)
                if item.get("status") in ("added", "modified", "renamed", "copied"):
                    files.append(item["filename"])
            page += 1
        return files

    def post_pr_review(
        self,
        repo: str,
        pr_number: int,
        commit_id: str,
        body: str,
        event: str,
        comments: list[dict[str, Any]]
    ) -> None:
        """
        Create a PR review with line-level comments.
        `event` can be "APPROVE", "REQUEST_CHANGES", or "COMMENT".
        """
        url = f"{self.api_url}/repos/{repo}/pulls/{pr_number}/reviews"
        payload = {
            "commit_id": commit_id,
            "body": body,
            "event": event,
            "comments": comments,
        }
        response = self.session.post(url, json=payload)
        response.raise_for_status()
