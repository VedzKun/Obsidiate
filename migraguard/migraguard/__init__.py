"""
MigraGuard — Static analysis for SQL migration files.

Flags risky schema operations (locking DDL, missing FK indexes,
irreversible drops) before they merge.
"""

__version__ = "0.1.0"
