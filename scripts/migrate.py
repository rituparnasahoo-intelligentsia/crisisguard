"""Apply pending database migrations.

A migration is a numbered .sql file in backend/migrations/. This script:
  1. creates a bookkeeping table, schema_migrations, if needed;
  2. applies every file that has not been applied yet, in filename order,
     each inside its own transaction (all-or-nothing);
  3. records each applied file with a checksum.

If a file that was already applied has since been edited, it stops with an error:
applied migrations must never change. Add a new numbered file instead.

Run from the project folder:  python -m scripts.migrate
"""

import hashlib
from pathlib import Path

from backend.database import get_connection

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "backend" / "migrations"
LOCK_ID = 7234001   # any fixed number; stops two migrators running at the same time


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def checksum_of(path: Path) -> str:
    # read_text normalises Windows (CRLF) line endings, so the checksum is the same on every machine.
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def apply_migrations(conn) -> list[str]:
    """Apply all pending migrations. Returns the names of the ones applied now."""
    conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version    TEXT PRIMARY KEY,
                checksum   TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        done = {r["version"]: r["checksum"]
                for r in conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()}

        applied_now = []
        for path in migration_files():
            digest = checksum_of(path)
            if path.name in done:
                if done[path.name] != digest:
                    raise RuntimeError(
                        f"Migration {path.name} was edited after it was applied. "
                        "Restore the original file and add a new migration instead."
                    )
                continue
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT INTO schema_migrations (version, checksum) VALUES (%s, %s)",
                    (path.name, digest),
                )
            applied_now.append(path.name)
        return applied_now
    finally:
        conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))


def main() -> None:
    with get_connection() as conn:
        applied = apply_migrations(conn)
        if applied:
            for name in applied:
                print(f"Applied {name}")
        else:
            print("Database is up to date. Nothing to apply.")


if __name__ == "__main__":
    main()
