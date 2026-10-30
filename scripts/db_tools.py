"""Small helpers shared by the init script, the reset script and the tests."""

from pathlib import Path

from psycopg import sql

SEED_FILE = Path(__file__).resolve().parent.parent / "backend" / "seed.sql"


def apply_seed(conn) -> None:
    """Insert the fictional demo data. Safe to repeat: existing rows are never overwritten."""
    conn.execute(SEED_FILE.read_text(encoding="utf-8"))


def application_tables(conn) -> list[str]:
    """Names of all application tables (everything except the migration bookkeeping table)."""
    rows = conn.execute(
        """
        SELECT table_name FROM information_schema.tables
         WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
           AND table_name <> 'schema_migrations'
         ORDER BY table_name
        """
    ).fetchall()
    return [r["table_name"] for r in rows]


def row_counts(conn) -> dict[str, int]:
    counts = {}
    for name in application_tables(conn):
        query = sql.SQL("SELECT count(*) AS n FROM {}").format(sql.Identifier(name))
        counts[name] = conn.execute(query).fetchone()["n"]
    return counts


def truncate_all_tables(conn) -> None:
    """DESTRUCTIVE: empties every application table. Only for tests and the reset script.
    Table names come from the database itself and are quoted with sql.Identifier."""
    names = application_tables(conn)
    if names:
        query = sql.SQL("TRUNCATE {} RESTART IDENTITY CASCADE").format(
            sql.SQL(", ").join(sql.Identifier(n) for n in names)
        )
        conn.execute(query)
