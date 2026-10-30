"""Reset the DEMO database: delete ALL application data and re-insert the fictional seed data.

This is destructive. It shows what will be deleted and asks you to type RESET.
It keeps the table structure (and the migration history) intact.
Run from the project folder:  python -m scripts.reset_demo

Optional backup first (PowerShell):
    docker compose exec db pg_dump -U crisisguard crisisguard > backup_demo.sql
"""

from backend.database import get_connection
from scripts.db_tools import apply_seed, row_counts, truncate_all_tables


def main() -> None:
    with get_connection() as conn:
        counts = row_counts(conn)
        for table, count in counts.items():
            if count:
                print(f"{table}: {count} rows will be deleted")
        print("The seed data will then be inserted again.")

        if input("Type RESET to continue: ").strip() != "RESET":
            print("Cancelled. Nothing was changed.")
            return

        with conn.transaction():
            truncate_all_tables(conn)
            apply_seed(conn)
        print("Demo data reset.")


if __name__ == "__main__":
    main()
