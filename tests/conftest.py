"""Shared test fixtures.

Safety rules for integration tests:
  - They use TEST_DATABASE_URL, never DATABASE_URL.
  - The test database name must end in "_test", otherwise the tests refuse to run,
    because each test wipes and re-seeds the tables.
  - If PostgreSQL is not reachable, integration tests are skipped (unit tests still run).
"""

import os
from pathlib import Path
from urllib.parse import urlparse

import psycopg
import pytest
from dotenv import load_dotenv

from backend import database
from backend.schemas import ProposalInput
from scripts.db_tools import apply_seed, truncate_all_tables
from scripts.migrate import apply_migrations

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def make_proposal(proposal_id: str, nurse_id: str,
                  incident: str = "Fictional incident: simulated emergency.") -> ProposalInput:
    return ProposalInput(proposal_id=proposal_id, incident_description=incident,
                         proposed_nurse_id=nurse_id)


@pytest.fixture(scope="session")
def test_db_url():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not set; skipping PostgreSQL integration tests.")
    if not urlparse(url).path.lstrip("/").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must point to a database whose name ends in '_test'.")
    if url == os.environ.get("DATABASE_URL"):
        pytest.fail("TEST_DATABASE_URL must not equal DATABASE_URL.")
    try:
        psycopg.connect(url, connect_timeout=3).close()
    except psycopg.OperationalError as exc:
        pytest.skip(f"Cannot connect to the test database: {exc}")
    return url


@pytest.fixture(scope="session")
def _schema(test_db_url):
    """Bring the test database's structure up to date using the real migrations."""
    with database.get_connection(test_db_url) as c:
        apply_migrations(c)


@pytest.fixture
def conn(test_db_url, _schema):
    """A connection to the TEST database, with tables emptied and re-seeded for each test."""
    with database.get_connection(test_db_url) as c:
        truncate_all_tables(c)
        apply_seed(c)
        yield c
