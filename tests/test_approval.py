"""PostgreSQL integration tests for the approval workflow.

Every test uses the isolated TEST database (see conftest.py).
"""

import threading

import pytest

from backend import approval, database
from backend.validator import validate_and_save_proposal
from tests.conftest import make_proposal

pytestmark = pytest.mark.integration


def test_valid_approval_updates_availability_and_version(conn):
    validate_and_save_proposal(conn, make_proposal("P1", "N01"))
    result = approval.approve_proposal(conn, "P1", "Reviewer 1", "looks fine")

    assert result.outcome == "committed"
    assert result.new_state_version == 2
    nurse = database.get_nurse(conn, "N01")
    assert nurse["available"] is False
    assert nurse["state_version"] == 2
    assert database.get_proposal(conn, "P1")["status"] == "approved"
    assert len(database.list_approvals(conn, "P1")) == 1


def test_invalid_proposal_cannot_be_approved(conn):
    validate_and_save_proposal(conn, make_proposal("P2", "N02"))   # unavailable nurse
    result = approval.approve_proposal(conn, "P2", "Reviewer 1")

    assert result.outcome == "rejected"
    assert database.get_proposal(conn, "P2")["status"] == "rejected_by_validator"
    assert database.get_nurse(conn, "N02")["state_version"] == 1    # untouched
    assert database.list_approvals(conn, "P2") == []


def test_nonexistent_nurse_proposal_is_stored_and_cannot_be_approved(conn):
    result = validate_and_save_proposal(conn, make_proposal("P3", "N99"))
    assert result.valid is False
    saved = database.get_proposal(conn, "P3")
    assert saved["proposed_nurse_id"] == "N99"
    assert "does not exist" in saved["validation_reason"]
    assert approval.approve_proposal(conn, "P3", "Reviewer 1").outcome == "rejected"


def test_reviewer_rejection_leaves_nurse_unchanged(conn):
    validate_and_save_proposal(conn, make_proposal("P4", "N03"))
    result = approval.reject_proposal(conn, "P4", "Reviewer 1", "not needed")

    assert result.outcome == "rejected"
    assert database.get_proposal(conn, "P4")["status"] == "rejected_by_reviewer"
    nurse = database.get_nurse(conn, "N03")
    assert nurse["available"] is True and nurse["state_version"] == 1
    assert database.list_approvals(conn, "P4")[0]["decision"] == "rejected"


def test_repeated_approval_does_not_change_state_twice(conn):
    validate_and_save_proposal(conn, make_proposal("P5", "N01"))
    first = approval.approve_proposal(conn, "P5", "Reviewer 1")
    second = approval.approve_proposal(conn, "P5", "Reviewer 1")

    assert first.outcome == "committed"
    assert second.outcome == "rejected"
    assert database.get_nurse(conn, "N01")["state_version"] == 2   # bumped once only
    assert len(database.list_approvals(conn, "P5")) == 1


def test_proposal_that_becomes_stale_is_not_committed(conn):
    validate_and_save_proposal(conn, make_proposal("P6", "N01"))
    # Meanwhile the real state changes (simulated by a direct update, as another workflow would).
    conn.execute("UPDATE nurses SET state_version = state_version + 1 WHERE nurse_id = 'N01'")

    result = approval.approve_proposal(conn, "P6", "Reviewer 1")
    assert result.outcome == "stale"
    assert database.get_proposal(conn, "P6")["status"] == "stale"
    assert database.get_nurse(conn, "N01")["available"] is True    # not assigned


def test_two_proposals_for_same_nurse_only_one_commits(conn):
    validate_and_save_proposal(conn, make_proposal("PA", "N01"))
    validate_and_save_proposal(conn, make_proposal("PB", "N01"))   # both valid at version 1

    first = approval.approve_proposal(conn, "PA", "Reviewer 1")
    second = approval.approve_proposal(conn, "PB", "Reviewer 2")

    assert first.outcome == "committed"
    assert second.outcome == "stale"
    assert database.get_nurse(conn, "N01")["state_version"] == 2


def _run_together(test_db_url, calls):
    """Run each (proposal_id, reviewer) approval in its own thread and connection,
    starting at the same moment. Returns the list of outcomes."""
    outcomes = []
    barrier = threading.Barrier(len(calls))

    def worker(proposal_id, reviewer):
        with database.get_connection(test_db_url) as c:
            barrier.wait()
            outcomes.append(approval.approve_proposal(c, proposal_id, reviewer).outcome)

    threads = [threading.Thread(target=worker, args=call) for call in calls]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return outcomes


def test_simultaneous_approvals_for_same_nurse_only_one_commits(conn, test_db_url):
    validate_and_save_proposal(conn, make_proposal("PA", "N01"))
    validate_and_save_proposal(conn, make_proposal("PB", "N01"))

    outcomes = _run_together(test_db_url, [("PA", "Reviewer 1"), ("PB", "Reviewer 2")])

    assert sorted(outcomes) == ["committed", "stale"]
    assert database.get_nurse(conn, "N01")["state_version"] == 2
    assert len(database.list_approvals(conn)) == 1


def test_simultaneous_double_click_on_same_proposal_commits_once(conn, test_db_url):
    validate_and_save_proposal(conn, make_proposal("PA", "N01"))

    outcomes = _run_together(test_db_url, [("PA", "Reviewer 1"), ("PA", "Reviewer 1")])

    assert sorted(outcomes) == ["committed", "rejected"]
    assert database.get_nurse(conn, "N01")["state_version"] == 2
    assert len(database.list_approvals(conn, "PA")) == 1


def test_database_failure_rolls_back_everything(conn, monkeypatch):
    validate_and_save_proposal(conn, make_proposal("P7", "N01"))
    real_add_audit_event = database.add_audit_event

    def failing_add_audit_event(c, action, proposal_id, details):
        if action == "assignment_committed":      # fail at the very last step
            raise RuntimeError("simulated database failure")
        real_add_audit_event(c, action, proposal_id, details)

    monkeypatch.setattr(database, "add_audit_event", failing_add_audit_event)

    with pytest.raises(RuntimeError):
        approval.approve_proposal(conn, "P7", "Reviewer 1")

    monkeypatch.undo()
    nurse = database.get_nurse(conn, "N01")
    assert nurse["available"] is True and nurse["state_version"] == 1   # nurse update undone
    assert database.get_proposal(conn, "P7")["status"] == "pending_review"
    assert database.list_approvals(conn, "P7") == []                    # approval row undone
    actions = [e["action"] for e in database.list_audit_events(conn, "P7")]
    assert "assignment_committed" not in actions and "reviewer_approved" not in actions
