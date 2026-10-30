"""Database access layer (PostgreSQL via psycopg 3).

Conventions used everywhere in this file:
- Every function takes `conn` (an open connection) as its first argument, so
  several calls can share ONE transaction.
- Connections are opened with autocommit=True. A multi-step change is wrapped in
  `with conn.transaction():` (see approval.py), which is an explicit
  BEGIN ... COMMIT block that rolls back automatically if an error happens.
- SQL uses %s placeholders and passes values separately. Values are never pasted
  into the SQL text, which prevents SQL injection.
- Rows come back as dictionaries (dict_row), e.g. nurse["available"].

Phase 4 Partial: Added hospital-wide read/write helpers, bundle proposals, 
and allocation records. Transaction orchestration remains in approval.py.
"""

import os
from typing import Optional

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

load_dotenv()  # reads the .env file in the project folder, if present


def get_connection(database_url: Optional[str] = None) -> psycopg.Connection:
    """Open a connection. Use it as: `with get_connection() as conn: ...`
    (the `with` block closes the connection for you)."""
    url = database_url or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set. Copy .env.example to .env and edit it.")
    return psycopg.connect(url, autocommit=True, row_factory=dict_row)


# ---------------------------------------------------------------- nurses (reads)

_NURSE_COLUMNS = "nurse_id, name, available, department, state_version"


def get_nurse(conn, nurse_id: str) -> Optional[dict]:
    """Return one nurse as a dict, or None if no such nurse exists."""
    cur = conn.execute(
        f"SELECT {_NURSE_COLUMNS} FROM nurses WHERE nurse_id = %s", (nurse_id,)
    )
    return cur.fetchone()


def list_nurses(conn) -> list[dict]:
    cur = conn.execute(f"SELECT {_NURSE_COLUMNS} FROM nurses ORDER BY nurse_id")
    return cur.fetchall()


def list_available_nurses(conn) -> list[dict]:
    cur = conn.execute(
        f"SELECT {_NURSE_COLUMNS} FROM nurses WHERE available = TRUE ORDER BY nurse_id"
    )
    return cur.fetchall()


def get_state_version(conn, nurse_id: str) -> Optional[int]:
    """Current state version of one nurse, or None if the nurse does not exist."""
    cur = conn.execute("SELECT state_version FROM nurses WHERE nurse_id = %s", (nurse_id,))
    row = cur.fetchone()
    return row["state_version"] if row else None


# ------------------------------------------------------------ nurses (the one write)

def mark_nurse_assigned(conn, nurse_id: str, expected_version: int) -> Optional[int]:
    """Conditionally mark a nurse unavailable.

    The UPDATE only changes the row if the nurse is STILL available AND still at
    the version the proposal was validated against. Check and change happen in a
    single statement, so two people cannot both succeed.

    Returns the new state version if the row was changed, or None if it was not
    (meaning the proposal is stale).
    """
    cur = conn.execute(
        """
        UPDATE nurses
           SET available = FALSE,
               state_version = state_version + 1
         WHERE nurse_id = %s
           AND available = TRUE
           AND state_version = %s
        RETURNING state_version
        """,
        (nurse_id, expected_version),
    )
    row = cur.fetchone()
    return row["state_version"] if row else None


# ---------------------------------------------------------------------- proposals

_PROPOSAL_COLUMNS = (
    "proposal_id, incident_description, proposed_nurse_id, validation_valid, "
    "validation_reason, state_version_used, status, created_at"
)


def save_proposal(
    conn,
    *,
    proposal_id: str,
    incident_description: str,
    proposed_nurse_id: str,
    valid: bool,
    reason: str,
    state_version_used: Optional[int],
    status: str,
) -> None:
    conn.execute(
        """
        INSERT INTO proposals
            (proposal_id, incident_description, proposed_nurse_id,
             validation_valid, validation_reason, state_version_used, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (proposal_id, incident_description, proposed_nurse_id,
         valid, reason, state_version_used, status),
    )


def get_proposal(conn, proposal_id: str, for_update: bool = False) -> Optional[dict]:
    """Return one proposal, or None.

    for_update=True adds `FOR UPDATE`, which LOCKS the row until the surrounding
    transaction ends. Other transactions that try to lock the same proposal wait.
    """
    sql = f"SELECT {_PROPOSAL_COLUMNS} FROM proposals WHERE proposal_id = %s"
    if for_update:
        sql += " FOR UPDATE"
    return conn.execute(sql, (proposal_id,)).fetchone()


def set_proposal_status(conn, proposal_id: str, status: str) -> None:
    conn.execute(
        "UPDATE proposals SET status = %s WHERE proposal_id = %s", (status, proposal_id)
    )


# ---------------------------------------------------------------------- approvals

def record_approval(conn, proposal_id: str, reviewer: str, decision: str, reason: str) -> int:
    """Store the reviewer's decision ('approved' or 'rejected'). Returns approval_id."""
    cur = conn.execute(
        """
        INSERT INTO approvals (proposal_id, reviewer, decision, reason)
        VALUES (%s, %s, %s, %s)
        RETURNING approval_id
        """,
        (proposal_id, reviewer, decision, reason),
    )
    return cur.fetchone()["approval_id"]


def list_approvals(conn, proposal_id: Optional[str] = None) -> list[dict]:
    if proposal_id is None:
        cur = conn.execute("SELECT * FROM approvals ORDER BY approval_id")
    else:
        cur = conn.execute(
            "SELECT * FROM approvals WHERE proposal_id = %s ORDER BY approval_id",
            (proposal_id,),
        )
    return cur.fetchall()


# -------------------------------------------------------------------- audit trail

def add_audit_event(conn, action: str, proposal_id: Optional[str], details: dict) -> None:
    """Append one audit event. `details` must be plain, non-sensitive data
    (never API keys or secrets). Jsonb() tells psycopg to store the dict as JSON."""
    conn.execute(
        "INSERT INTO audit_logs (proposal_id, action, details) VALUES (%s, %s, %s)",
        (proposal_id, action, Jsonb(details)),
    )


def list_audit_events(conn, proposal_id: Optional[str] = None) -> list[dict]:
    """All events in order, or only the events for one proposal."""
    if proposal_id is None:
        cur = conn.execute("SELECT * FROM audit_logs ORDER BY event_id")
    else:
        cur = conn.execute(
            "SELECT * FROM audit_logs WHERE proposal_id = %s ORDER BY event_id",
            (proposal_id,),
        )
    return cur.fetchall()


# =================================================================================
# NEW: PHASE 4 - HOSPITAL WIDE RESOURCES
# =================================================================================

# ------------------------------------------------------------------ hospitals / wards

def get_hospital(conn, hospital_id: str) -> Optional[dict]:
    return conn.execute("SELECT * FROM hospitals WHERE hospital_id = %s", (hospital_id,)).fetchone()

def list_hospitals(conn) -> list[dict]:
    return conn.execute("SELECT * FROM hospitals ORDER BY hospital_id").fetchall()

def get_ward(conn, ward_id: str) -> Optional[dict]:
    return conn.execute("SELECT * FROM wards WHERE ward_id = %s", (ward_id,)).fetchone()

def list_wards(conn, hospital_id: Optional[str] = None) -> list[dict]:
    if hospital_id:
        return conn.execute("SELECT * FROM wards WHERE hospital_id = %s ORDER BY ward_id", (hospital_id,)).fetchall()
    return conn.execute("SELECT * FROM wards ORDER BY ward_id").fetchall()

# ------------------------------------------------------------------ beds

def get_bed(conn, bed_id: str) -> Optional[dict]:
    return conn.execute("SELECT * FROM beds WHERE bed_id = %s", (bed_id,)).fetchone()

def list_beds(conn, hospital_id: Optional[str] = None, status: Optional[str] = None) -> list[dict]:
    sql = "SELECT * FROM beds WHERE 1=1"
    params = []
    if hospital_id:
        sql += " AND hospital_id = %s"
        params.append(hospital_id)
    if status:
        sql += " AND status = %s"
        params.append(status)
    sql += " ORDER BY bed_id"
    return conn.execute(sql, tuple(params)).fetchall()

def list_free_beds(conn, hospital_id: Optional[str] = None) -> list[dict]:
    return list_beds(conn, hospital_id=hospital_id, status="free")

def mark_bed_reserved(conn, bed_id: str, expected_version: int) -> Optional[int]:
    """Conditionally reserve a bed. Returns new version, or None if stale/unavailable."""
    cur = conn.execute(
        """
        UPDATE beds
           SET status = 'reserved',
               state_version = state_version + 1
         WHERE bed_id = %s
           AND status = 'free'
           AND state_version = %s
        RETURNING state_version
        """,
        (bed_id, expected_version),
    )
    row = cur.fetchone()
    return row["state_version"] if row else None

# ------------------------------------------------------------------ doctors

def get_doctor(conn, doctor_id: str) -> Optional[dict]:
    return conn.execute("SELECT * FROM doctors WHERE doctor_id = %s", (doctor_id,)).fetchone()

def list_doctors(conn, hospital_id: Optional[str] = None, available_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM doctors WHERE 1=1"
    params = []
    if hospital_id:
        sql += " AND hospital_id = %s"
        params.append(hospital_id)
    if available_only:
        sql += " AND available = TRUE"
    sql += " ORDER BY doctor_id"
    return conn.execute(sql, tuple(params)).fetchall()

def touch_doctor_version(conn, doctor_id: str, expected_version: int) -> Optional[int]:
    cur = conn.execute(
        """
        UPDATE doctors
           SET state_version = state_version + 1
         WHERE doctor_id = %s
           AND available = TRUE
           AND state_version = %s
        RETURNING state_version
        """,
        (doctor_id, expected_version),
    )
    row = cur.fetchone()
    return row["state_version"] if row else None

# ------------------------------------------------------------------ equipment

def get_equipment_unit(conn, unit_id: str) -> Optional[dict]:
    return conn.execute("SELECT * FROM equipment_units WHERE unit_id = %s", (unit_id,)).fetchone()

def list_equipment_units(conn, hospital_id: Optional[str] = None, type_id: Optional[str] = None, status: Optional[str] = None) -> list[dict]:
    sql = "SELECT * FROM equipment_units WHERE 1=1"
    params = []
    if hospital_id:
        sql += " AND hospital_id = %s"
        params.append(hospital_id)
    if type_id:
        sql += " AND type_id = %s"
        params.append(type_id)
    if status:
        sql += " AND status = %s"
        params.append(status)
    sql += " ORDER BY unit_id"
    return conn.execute(sql, tuple(params)).fetchall()

def mark_equipment_reserved(conn, unit_id: str, expected_version: int) -> Optional[int]:
    """Conditionally reserve equipment. Returns new version, or None if stale/unavailable."""
    cur = conn.execute(
        """
        UPDATE equipment_units
           SET status = 'reserved',
               state_version = state_version + 1
         WHERE unit_id = %s
           AND status = 'available'
           AND state_version = %s
        RETURNING state_version
        """,
        (unit_id, expected_version),
    )
    row = cur.fetchone()
    return row["state_version"] if row else None

# ------------------------------------------------------------------ incidents / patients

def get_incident(conn, incident_id: str) -> Optional[dict]:
    return conn.execute("SELECT * FROM incidents WHERE incident_id = %s", (incident_id,)).fetchone()

def list_incidents(conn, hospital_id: Optional[str] = None, status: Optional[str] = None) -> list[dict]:
    sql = "SELECT * FROM incidents WHERE 1=1"
    params = []
    if hospital_id:
        sql += " AND hospital_id = %s"
        params.append(hospital_id)
    if status:
        sql += " AND status = %s"
        params.append(status)
    sql += " ORDER BY arrival_time DESC"
    return conn.execute(sql, tuple(params)).fetchall()

def get_patient(conn, patient_id: str) -> Optional[dict]:
    return conn.execute("SELECT * FROM patients WHERE patient_id = %s", (patient_id,)).fetchone()

def list_incident_patients(conn, incident_id: str) -> list[dict]:
    cur = conn.execute(
        """
        SELECT p.*, ip.reported_condition 
          FROM patients p
          JOIN incident_patients ip ON p.patient_id = ip.patient_id
         WHERE ip.incident_id = %s
        """, 
        (incident_id,)
    )
    return cur.fetchall()

# ------------------------------------------------------------------ bundle proposals

def save_bundle_proposal(
    conn,
    *,
    proposal_id: str,
    incident_id: str,
    patient_id: str,
    explanation: str,
    input_snapshot: dict,
    plan_label: str = "preferred",
    valid: bool = False,
    reason: str = "",
    status: str = "pending_review"
) -> None:
    conn.execute(
        """
        INSERT INTO proposals
            (proposal_id, incident_description, proposed_nurse_id, validation_valid, 
             validation_reason, status, proposal_kind, incident_id, patient_id, 
             explanation, input_snapshot, plan_label)
        VALUES (%s, 'Bundle proposal', NULL, %s, %s, %s, 'bundle', %s, %s, %s, %s, %s)
        """,
        (proposal_id, valid, reason, status, incident_id, patient_id, 
         explanation, Jsonb(input_snapshot), plan_label),
    )

def add_proposal_item(conn, proposal_id: str, resource_type: str, resource_id: str, version_used: Optional[int]) -> None:
    conn.execute(
        """
        INSERT INTO proposal_items (proposal_id, resource_type, resource_id, version_used)
        VALUES (%s, %s, %s, %s)
        """,
        (proposal_id, resource_type, resource_id, version_used),
    )

def list_proposal_items(conn, proposal_id: str) -> list[dict]:
    return conn.execute("SELECT * FROM proposal_items WHERE proposal_id = %s ORDER BY item_id", (proposal_id,)).fetchall()

# ------------------------------------------------------------------ allocations

def create_allocation(conn, *, hospital_id: str, incident_id: str, patient_id: str, proposal_id: str) -> int:
    cur = conn.execute(
        """
        INSERT INTO allocations (hospital_id, incident_id, patient_id, proposal_id)
        VALUES (%s, %s, %s, %s)
        RETURNING allocation_id
        """,
        (hospital_id, incident_id, patient_id, proposal_id),
    )
    return cur.fetchone()["allocation_id"]

def add_allocation_item_bed(conn, allocation_id: int, hospital_id: str, bed_id: str) -> None:
    conn.execute(
        "INSERT INTO allocation_items (allocation_id, hospital_id, resource_type, bed_id) VALUES (%s, %s, 'bed', %s)",
        (allocation_id, hospital_id, bed_id),
    )

def add_allocation_item_doctor(conn, allocation_id: int, hospital_id: str, doctor_id: str) -> None:
    conn.execute(
        "INSERT INTO allocation_items (allocation_id, hospital_id, resource_type, doctor_id) VALUES (%s, %s, 'doctor', %s)",
        (allocation_id, hospital_id, doctor_id),
    )

def add_allocation_item_nurse(conn, allocation_id: int, hospital_id: str, nurse_id: str) -> None:
    conn.execute(
        "INSERT INTO allocation_items (allocation_id, hospital_id, resource_type, nurse_id) VALUES (%s, %s, 'nurse', %s)",
        (allocation_id, hospital_id, nurse_id),
    )

def add_allocation_item_equipment(conn, allocation_id: int, hospital_id: str, equipment_unit_id: str) -> None:
    conn.execute(
        "INSERT INTO allocation_items (allocation_id, hospital_id, resource_type, equipment_unit_id) VALUES (%s, %s, 'equipment', %s)",
        (allocation_id, hospital_id, equipment_unit_id),
    )

def get_allocation(conn, allocation_id: int) -> Optional[dict]:
    return conn.execute("SELECT * FROM allocations WHERE allocation_id = %s", (allocation_id,)).fetchone()

def list_allocations(conn, patient_id: Optional[str] = None, incident_id: Optional[str] = None) -> list[dict]:
    sql = "SELECT * FROM allocations WHERE 1=1"
    params = []
    if patient_id:
        sql += " AND patient_id = %s"
        params.append(patient_id)
    if incident_id:
        sql += " AND incident_id = %s"
        params.append(incident_id)
    sql += " ORDER BY allocation_id"
    return conn.execute(sql, tuple(params)).fetchall()

def list_allocation_items(conn, allocation_id: int) -> list[dict]:
    return conn.execute("SELECT * FROM allocation_items WHERE allocation_id = %s ORDER BY item_id", (allocation_id,)).fetchall()
def save_incident(conn, report) -> None:
    """Saves an incoming EmergencyReport to the incidents table."""
    conn.execute(
        """
        INSERT INTO incidents (incident_id, hospital_id, emergency_type, reported_severity, arrival_time, description)
        VALUES (%s, %s, %s, %s, now(), %s)
        """,
        (report.incident_id, report.hospital_id, "unknown", report.reported_severity, report.description)
    )