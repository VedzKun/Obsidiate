from pathlib import Path
from migraguard.ci.diff import filter_migration_files


def test_filter_migration_files_exact_match():
    files = ["migrations/001_init.sql", "src/main.py", "db/migrate/002_add_table.sql"]
    
    # Test simple glob
    filtered = filter_migration_files(files, "migrations/*.sql")
    assert len(filtered) == 1
    assert filtered[0] == Path("migrations/001_init.sql")

def test_filter_migration_files_recursive_glob():
    files = ["migrations/001_init.sql", "src/main.py", "db/migrate/002_add_table.sql", "README.md"]
    
    # Test **/*.sql
    filtered = filter_migration_files(files, "**/*.sql")
    assert len(filtered) == 2
    assert Path("migrations/001_init.sql") in filtered
    assert Path("db/migrate/002_add_table.sql") in filtered
