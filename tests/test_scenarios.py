"""Scenario tests: the seeded evaluation (unit) and audit-trail checks (integration)."""

from pathlib import Path

import pytest

from backend import approval, database, evaluation
from backend.validator import validate_and_save_proposal
from tests.conftest import make_proposal


# ------------------------------------------------------------------ unit (no database)

def test_all_seeded_evaluation_scenarios_pass():
    results = evaluation.run_scenarios()
    failures = [r for r in results if not r["passed"]]
    assert failures == []


# ----------------------------------------------------------- integration (PostgreSQL)

@pytest.mark.integration
def test_seed_sql_matches_evaluation_fixture(conn):
    # The seed now also contains nurses for a second hospital; compare the original three.
    nurses = {n["nurse_id"]: n for n in database.list_nurses(conn)
              if n["nurse_id"] in evaluation.SEED_NURSES}
    assert nurses == evaluation.SEED_NURSES


@pytest.mark.integration
def test_read_functions(conn):
    available = [n["nurse_id"] for n in database.list_available_nurses(conn)]
    assert "N01" in available and "N03" in available and "N02" not in available
    assert database.get_nurse(conn, "N99") is None
    assert database.get_state_version(conn, "N01") == 1


@pytest.mark.integration
def test_audit_trail_for_successful_workflow(conn):
    validate_and_save_proposal(conn, make_proposal("P1", "N01"))
    approval.approve_proposal(conn, "P1", "Reviewer 1", "ok")
    actions = [e["action"] for e in database.list_audit_events(conn, "P1")]
    assert actions == ["proposal_created", "validation_passed",
                       "reviewer_approved", "assignment_committed"]


@pytest.mark.integration
def test_audit_trail_for_validation_failure(conn):
    validate_and_save_proposal(conn, make_proposal("P2", "N99"))
    events = database.list_audit_events(conn, "P2")
    assert [e["action"] for e in events] == ["proposal_created", "validation_failed"]
    assert "does not exist" in events[1]["details"]["reason"]
    assert events[1]["created_at"] is not None


@pytest.mark.integration
def test_audit_trail_for_stale_approval(conn):
    validate_and_save_proposal(conn, make_proposal("P3", "N01"))
    conn.execute("UPDATE nurses SET state_version = state_version + 1 WHERE nurse_id = 'N01'")
    approval.approve_proposal(conn, "P3", "Reviewer 1")
    events = database.list_audit_events(conn, "P3")
    assert events[-1]["action"] == "approval_failed_stale"
    assert events[-1]["details"]["saved_version"] == 1
    assert events[-1]["details"]["current_version"] == 2


@pytest.mark.integration
def test_audit_trail_for_repeated_approval_and_rejection(conn):
    validate_and_save_proposal(conn, make_proposal("P4", "N01"))
    approval.approve_proposal(conn, "P4", "Reviewer 1")
    approval.approve_proposal(conn, "P4", "Reviewer 1")
    assert database.list_audit_events(conn, "P4")[-1]["action"] == "approval_blocked"

    validate_and_save_proposal(conn, make_proposal("P5", "N03"))
    approval.reject_proposal(conn, "P5", "Reviewer 1", "not needed")
    assert database.list_audit_events(conn, "P5")[-1]["action"] == "reviewer_rejected"


@pytest.mark.integration
def test_database_constraints_block_approving_an_invalid_proposal(conn):
    """Even raw SQL cannot mark an invalid proposal 'approved' (CHECK constraint)."""
    import psycopg
    validate_and_save_proposal(conn, make_proposal("P6", "N02"))
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE proposals SET status = 'approved' WHERE proposal_id = 'P6'")


@pytest.mark.integration
def test_duplicate_proposal_id_is_refused(conn):
    validate_and_save_proposal(conn, make_proposal("P7", "N01"))
    with pytest.raises(ValueError):
        validate_and_save_proposal(conn, make_proposal("P7", "N03"))
