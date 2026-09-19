from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml


class Config:
    def __init__(self, migration_pattern: str, blocking_severities: list[str]) -> None:
        self.migration_pattern = migration_pattern
        self.blocking_severities = [s.lower() for s in blocking_severities]

    @classmethod
    def load(cls, path: Path | str = ".migraguard.yml") -> Config:
        """Load configuration from a YAML file, falling back to defaults if missing."""
        default_pattern = "**/*.sql"
        default_severities = ["high", "critical"]

        config_path = Path(path)
        if not config_path.is_file():
            return cls(default_pattern, default_severities)

        try:
            with config_path.open("r", encoding="utf-8") as f:
                data: dict[str, Any] = yaml.safe_load(f) or {}
        except Exception:
            # If there's an error parsing, return defaults
            return cls(default_pattern, default_severities)

        migration_pattern = data.get("migration_pattern", default_pattern)
        blocking_severities = data.get("blocking_severities", default_severities)

        if not isinstance(blocking_severities, list):
            blocking_severities = default_severities

        return cls(migration_pattern, blocking_severities)
