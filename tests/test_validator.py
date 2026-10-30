"""Unit tests for the validator. No database needed."""

from backend.hospital_state import is_state_current
from backend.validator import validate_against_record
from tests.conftest import make_proposal

AVAILABLE_A = {"nurse_id": "N01", "name": "Person A", "available": True, "department": "Emergency", "state_version": 1}
UNAVAILABLE_B = {"nurse_id": "N02", "name": "Person B", "available": False, "department": "ICU", "state_version": 1}
AVAILABLE_C = {"nurse_id": "N03", "name": "Person C", "available": True, "department": "Emergency", "state_version": 1}


def test_available_person_a_is_valid():
    result = validate_against_record(make_proposal("P1", "N01"), AVAILABLE_A)
    assert result.valid is True
    assert result.state_version == 1
    assert result.nurse_id == "N01"


def test_unavailable_person_b_is_invalid():
    result = validate_against_record(make_proposal("P2", "N02"), UNAVAILABLE_B)
    assert result.valid is False
    assert "unavailable" in result.reason


def test_available_person_c_is_valid():
    result = validate_against_record(make_proposal("P3", "N03"), AVAILABLE_C)
    assert result.valid is True


def test_nonexistent_nurse_is_invalid_with_distinct_reason():
    result = validate_against_record(make_proposal("P4", "N99"), None)
    assert result.valid is False
    assert "does not exist" in result.reason
    assert result.state_version is None


def test_nonexistent_and_unavailable_have_different_reasons():
    missing = validate_against_record(make_proposal("P5", "N99"), None)
    busy = validate_against_record(make_proposal("P6", "N02"), UNAVAILABLE_B)
    assert missing.reason != busy.reason


def test_blank_nurse_id_is_invalid():
    result = validate_against_record(make_proposal("P7", "   "), None)
    assert result.valid is False
    assert "empty" in result.reason


def test_blank_incident_description_is_invalid():
    result = validate_against_record(make_proposal("P8", "N01", incident="  "), AVAILABLE_A)
    assert result.valid is False


def test_ai_supplied_state_version_is_ignored():
    # The AI tries to smuggle in a version. It is dropped; the result uses the database value.
    from backend.schemas import ProposalInput
    proposal = ProposalInput(proposal_id="P9", incident_description="x",
                             proposed_nurse_id="N01", state_version=999)
    assert not hasattr(proposal, "state_version")
    assert validate_against_record(proposal, AVAILABLE_A).state_version == 1


def test_is_state_current():
    assert is_state_current(1, 1) is True
    assert is_state_current(1, 2) is False
    assert is_state_current(None, 1) is False
    assert is_state_current(1, None) is False
