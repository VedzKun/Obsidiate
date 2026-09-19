from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path


def filter_migration_files(files: list[str], pattern: str) -> list[Path]:
    """Filter a list of file paths by a glob pattern and return Path objects."""
    # We use fnmatch or Path.match. For `**/*.sql`, Path.match is usually fine in Python 3.11+, 
    # but sometimes fnmatch is easier for simple globs, or we can use pathlib's glob syntax manually.
    # To support `**/*.sql` properly, let's use a simple approach: if it ends with .sql and 
    # matches the pattern. Actually, `pathlib.PurePath.match` handles `*` and `**` differently 
    # depending on the python version. Let's just use `fnmatch` if it's a simple glob, or 
    # better yet, since `pattern` is a glob, we can use `wcmatch` or just simple `fnmatch`.
    # Standard fnmatch does not support `**` across directories well.
    # A robust way is to just use Path(f).match(pattern) in python 3.11+.
    # Actually, `migrations/*.sql` or `**/*.sql`. 
    filtered = []
    for f in files:
        p = Path(f)
        # Check if the file matches the glob pattern
        if p.match(pattern):
            filtered.append(p)
    return filtered


def get_changed_files_local(base_branch: str) -> list[str]:
    """Get changed files comparing HEAD to a base branch using git."""
    try:
        # Use git diff to find names of changed files
        cmd = ["git", "diff", "--name-only", f"{base_branch}...HEAD"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to get git diff: {e.stderr}") from e
