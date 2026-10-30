"""Create/upgrade the tables and insert the fictional demo data.

Run from the project folder:  python -m scripts.init_db

Safe to run again: pending migrations are applied once, and the seed never deletes
or overwrites existing rows. Before upgrading a database that holds data you care
about, take a backup (see README).
"""

from backend.database import get_connection
from scripts.db_tools import apply_seed, row_counts
from scripts.migrate import apply_migrations


def main() -> None:
    with get_connection() as conn:
        applied = apply_migrations(conn)
        print("Applied migrations:", ", ".join(applied) if applied else "none (already up to date)")
        apply_seed(conn)
        print("Seed data applied (existing rows left untouched).")
        print("\nRow counts:")
        for table, count in row_counts(conn).items():
            print(f"  {table:<20} {count}")


if __name__ == "__main__":
    main()
