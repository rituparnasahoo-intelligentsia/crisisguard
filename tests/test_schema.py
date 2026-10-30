"""PostgreSQL integration tests for the hospital-wide schema (migrations 001-002) and seed.

Each test proves that the DATABASE ITSELF refuses an invalid state, independent of any
Python validation. All run against the isolated test database (see conftest.py).
"""

import psycopg
import pytest

from scripts import migrate
from scripts.db_tools import apply_seed, row_counts

pytestmark = pytest.mark.integration

errors = psycopg.errors


# ------------------------------------------------------------------ small helpers

def add_bundle_proposal(conn, proposal_id, patient_id="PT-001", incident_id="INC-001"):
    conn.execute(
        """
        INSERT INTO proposals (proposal_id, incident_description, proposed_nurse_id,
                               validation_valid, validation_reason, state_version_used,
                               status, proposal_kind, incident_id, patient_id)
        VALUES (%s, 'fictional bundle', NULL, TRUE, 'ok', NULL,
                'pending_review', 'bundle', %s, %s)
        """,
        (proposal_id, incident_id, patient_id),
    )


def add_allocation(conn, proposal_id, patient_id="PT-001", incident_id="INC-001", hospital_id="H01"):
    add_bundle_proposal(conn, proposal_id, patient_id, incident_id)
    return conn.execute(
        """
        INSERT INTO allocations (hospital_id, incident_id, patient_id, proposal_id)
        VALUES (%s, %s, %s, %s) RETURNING allocation_id
        """,
        (hospital_id, incident_id, patient_id, proposal_id),
    ).fetchone()["allocation_id"]


def add_bed_item(conn, allocation_id, bed_id, hospital_id="H01"):
    conn.execute(
        """
        INSERT INTO allocation_items (allocation_id, hospital_id, resource_type, bed_id)
        VALUES (%s, %s, 'bed', %s)
        """,
        (allocation_id, hospital_id, bed_id),
    )


# ------------------------------------------------------------- migrations and seed

def test_migrations_are_recorded_and_repeatable(conn):
    versions = [r["version"] for r in
                conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()]
    assert versions == ["001_nurse_only_baseline.sql", "002_hospital_wide.sql"]
    assert migrate.apply_migrations(conn) == []          # nothing pending


def test_edited_migration_is_detected(conn):
    name = "002_hospital_wide.sql"
    real = migrate.checksum_of(migrate.MIGRATIONS_DIR / name)
    conn.execute("UPDATE schema_migrations SET checksum = 'tampered' WHERE version = %s", (name,))
    try:
        with pytest.raises(RuntimeError, match="edited after it was applied"):
            migrate.apply_migrations(conn)
    finally:
        conn.execute("UPDATE schema_migrations SET checksum = %s WHERE version = %s", (real, name))


def test_seed_row_counts(conn):
    counts = row_counts(conn)
    expected = {"hospitals": 2, "wards": 6, "beds": 25, "nurses": 6, "doctors": 6,
                "equipment_types": 4, "equipment_units": 8, "patients": 3,
                "incidents": 2, "incident_patients": 3, "policy_settings": 3,
                "proposals": 0, "allocations": 0, "audit_logs": 0}
    for table, n in expected.items():
        assert counts[table] == n, table


def test_seed_has_realistic_shortages(conn):
    beds = {r["bed_id"]: r["status"] for r in conn.execute("SELECT bed_id, status FROM beds").fetchall()}
    assert beds["B-H01-ED-06"] == "out_of_service"
    assert beds["B-H02-GEN-04"] == "cleaning"
    assert sum(1 for s in beds.values() if s == "free") == 23
    unit = conn.execute("SELECT status FROM equipment_units WHERE unit_id = 'VENT-H01-02'").fetchone()
    assert unit["status"] == "maintenance"


def test_seed_is_repeatable_and_never_overwrites(conn):
    conn.execute("UPDATE beds SET status = 'occupied' WHERE bed_id = 'B-H01-ED-01'")
    before = row_counts(conn)
    apply_seed(conn)
    assert row_counts(conn) == before
    status = conn.execute("SELECT status FROM beds WHERE bed_id = 'B-H01-ED-01'").fetchone()["status"]
    assert status == "occupied"


# ---------------------------------------------------- hospital / ward / bed integrity

def test_resource_cannot_use_a_ward_from_another_hospital(conn):
    with pytest.raises(errors.ForeignKeyViolation):
        conn.execute(
            "INSERT INTO equipment_units (unit_id, type_id, hospital_id, ward_id) "
            "VALUES ('E-X', 'ventilator', 'H02', 'W-H01-ICU')"
        )


def test_ward_capacity_is_enforced(conn):
    with pytest.raises(errors.RaiseException, match="at capacity"):
        conn.execute(
            "INSERT INTO beds (bed_id, hospital_id, ward_id, bed_type) "
            "VALUES ('B-EXTRA', 'H01', 'W-H01-ICU', 'icu')"
        )


def test_bed_type_must_match_ward_type(conn):
    conn.execute("DELETE FROM beds WHERE bed_id = 'B-H01-GEN-06'")      # make room first
    with pytest.raises(errors.RaiseException, match="does not match"):
        conn.execute(
            "INSERT INTO beds (bed_id, hospital_id, ward_id, bed_type) "
            "VALUES ('B-WRONG', 'H01', 'W-H01-GEN', 'icu')"
        )
    conn.execute(      # the correct type fits in the free slot
        "INSERT INTO beds (bed_id, hospital_id, ward_id, bed_type) "
        "VALUES ('B-H01-GEN-06', 'H01', 'W-H01-GEN', 'general')"
    )


def test_invalid_bed_status_is_refused(conn):
    with pytest.raises(errors.CheckViolation):
        conn.execute("UPDATE beds SET status = 'teleported' WHERE bed_id = 'B-H01-ED-01'")


def test_only_fictional_patients_can_be_stored(conn):
    with pytest.raises(errors.CheckViolation):
        conn.execute(
            "INSERT INTO patients (patient_id, display_name, is_fictional) "
            "VALUES ('PT-REAL', 'Not fictional', FALSE)"
        )


# ------------------------------------------------------------------- allocations

def test_one_active_allocation_per_patient(conn):
    add_allocation(conn, "PB1", patient_id="PT-001")
    add_bundle_proposal(conn, "PB2", patient_id="PT-001")
    with pytest.raises(errors.UniqueViolation):
        conn.execute(
            "INSERT INTO allocations (hospital_id, incident_id, patient_id, proposal_id) "
            "VALUES ('H01', 'INC-001', 'PT-001', 'PB2')"
        )


def test_patient_must_belong_to_the_incident(conn):
    add_bundle_proposal(conn, "PB1", patient_id="PT-003", incident_id="INC-002")  # valid pairing
    with pytest.raises(errors.ForeignKeyViolation):      # PT-003 is not part of INC-001
        conn.execute(
            "INSERT INTO allocations (hospital_id, incident_id, patient_id, proposal_id) "
            "VALUES ('H01', 'INC-001', 'PT-003', 'PB1')"
        )


def test_active_allocation_must_not_have_an_end_time(conn):
    add_bundle_proposal(conn, "PB1")
    with pytest.raises(errors.CheckViolation):
        conn.execute(
            "INSERT INTO allocations (hospital_id, incident_id, patient_id, proposal_id, status) "
            "VALUES ('H01', 'INC-001', 'PT-001', 'PB1', 'released')"      # released but no ended_at
        )


def test_same_bed_cannot_be_actively_allocated_twice(conn):
    first = add_allocation(conn, "PB1", patient_id="PT-001")
    second = add_allocation(conn, "PB2", patient_id="PT-002")
    add_bed_item(conn, first, "B-H01-ICU-01")
    with pytest.raises(errors.UniqueViolation):
        add_bed_item(conn, second, "B-H01-ICU-01")

    # Once the first item is released, the bed can be allocated again.
    conn.execute("UPDATE allocation_items SET status = 'released' WHERE allocation_id = %s", (first,))
    add_bed_item(conn, second, "B-H01-ICU-01")


def test_same_equipment_unit_cannot_be_actively_allocated_twice(conn):
    first = add_allocation(conn, "PB1", patient_id="PT-001")
    second = add_allocation(conn, "PB2", patient_id="PT-002")
    sql = ("INSERT INTO allocation_items (allocation_id, hospital_id, resource_type, equipment_unit_id) "
           "VALUES (%s, 'H01', 'equipment', 'VENT-H01-01')")
    conn.execute(sql, (first,))
    with pytest.raises(errors.UniqueViolation):
        conn.execute(sql, (second,))


def test_an_allocation_has_at_most_one_active_bed(conn):
    allocation = add_allocation(conn, "PB1")
    add_bed_item(conn, allocation, "B-H01-ICU-01")
    with pytest.raises(errors.UniqueViolation):
        add_bed_item(conn, allocation, "B-H01-ICU-02")


def test_allocated_resource_must_belong_to_the_allocation_hospital(conn):
    allocation = add_allocation(conn, "PB1")                    # a hospital H01 allocation
    with pytest.raises(errors.ForeignKeyViolation):             # bed B-H02-ICU-01 belongs to H02
        add_bed_item(conn, allocation, "B-H02-ICU-01", hospital_id="H01")


def test_allocation_item_must_fill_exactly_the_matching_resource_column(conn):
    allocation = add_allocation(conn, "PB1")
    with pytest.raises(errors.CheckViolation):                  # type 'bed' but a doctor given
        conn.execute(
            "INSERT INTO allocation_items (allocation_id, hospital_id, resource_type, doctor_id) "
            "VALUES (%s, 'H01', 'bed', 'D01')", (allocation,))
    with pytest.raises(errors.CheckViolation):                  # type 'bed' but nothing given
        conn.execute(
            "INSERT INTO allocation_items (allocation_id, hospital_id, resource_type) "
            "VALUES (%s, 'H01', 'bed')", (allocation,))


# ---------------------------------------------------------------------- proposals

def test_bundle_proposal_needs_incident_and_patient(conn):
    with pytest.raises(errors.CheckViolation):
        conn.execute(
            "INSERT INTO proposals (proposal_id, incident_description, validation_valid, "
            "validation_reason, status, proposal_kind) "
            "VALUES ('PB1', 'x', TRUE, 'ok', 'pending_review', 'bundle')"
        )


def test_nurse_only_proposal_still_needs_a_nurse(conn):
    with pytest.raises(errors.CheckViolation):
        conn.execute(
            "INSERT INTO proposals (proposal_id, incident_description, validation_valid, "
            "validation_reason, state_version_used, status) "
            "VALUES ('PN1', 'x', TRUE, 'ok', 1, 'pending_review')"
        )


def test_proposal_items_can_name_resources_that_do_not_exist(conn):
    add_bundle_proposal(conn, "PB1")
    conn.execute(      # the AI invented this bed; it must still be storable for auditing
        "INSERT INTO proposal_items (proposal_id, resource_type, resource_id) "
        "VALUES ('PB1', 'bed', 'B-DOES-NOT-EXIST')"
    )
    with pytest.raises(errors.UniqueViolation):     # but the same item twice is refused
        conn.execute(
            "INSERT INTO proposal_items (proposal_id, resource_type, resource_id) "
            "VALUES ('PB1', 'bed', 'B-DOES-NOT-EXIST')"
        )


def test_reviewer_can_record_a_revision_request(conn):
    add_bundle_proposal(conn, "PB1")
    conn.execute(
        "INSERT INTO approvals (proposal_id, reviewer, decision, reason) "
        "VALUES ('PB1', 'Reviewer 1', 'revision_requested', 'Please try another ward')"
    )
    conn.execute("UPDATE proposals SET status = 'superseded' WHERE proposal_id = 'PB1'")


# -------------------------------------------------------------------- audit trail

def test_audit_logs_are_append_only(conn):
    conn.execute("INSERT INTO audit_logs (action, actor, entity_type, entity_id) "
                 "VALUES ('test_event', 'tester', 'bed', 'B-H01-ED-01')")
    with pytest.raises(errors.RaiseException, match="append-only"):
        conn.execute("UPDATE audit_logs SET action = 'changed'")
    with pytest.raises(errors.RaiseException, match="append-only"):
        conn.execute("DELETE FROM audit_logs")
    assert conn.execute("SELECT count(*) AS n FROM audit_logs").fetchone()["n"] == 1
