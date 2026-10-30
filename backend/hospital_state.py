"""Resource state: how the rest of the backend reads "what is true right now".

The database is the source of truth. Nothing here caches data in Python.

How state versions work:
  - Every resource row has a state_version, starting at 1.
  - Each time the row changes, the version goes up by 1.
  - A proposal remembers the version it was validated against.
  - If the current version differs from the remembered one, the proposal is STALE.
"""

from typing import Optional
from backend import database

# ------------------------------------------------------------------ OLD: Nurses

def get_nurse_state(conn, nurse_id: str) -> Optional[dict]:
    return database.get_nurse(conn, nurse_id)

def get_all_nurse_states(conn) -> list[dict]:
    return database.list_nurses(conn)

def get_available_nurse_states(conn) -> list[dict]:
    return database.list_available_nurses(conn)

def get_state_version(conn, nurse_id: str) -> Optional[int]:
    return database.get_state_version(conn, nurse_id)

def is_state_current(saved_version: Optional[int], current_version: Optional[int]) -> bool:
    """True only if both versions exist and are equal. A pure function: no database."""
    return saved_version is not None and saved_version == current_version

# ------------------------------------------------------------------ NEW: Hospital-Wide

def get_hospital_state(conn, hospital_id: str) -> Optional[dict]:
    return database.get_hospital(conn, hospital_id)

def get_bed_state(conn, bed_id: str) -> Optional[dict]:
    return database.get_bed(conn, bed_id)

def get_available_beds(conn, hospital_id: str) -> list[dict]:
    return database.list_free_beds(conn, hospital_id)

def get_doctor_state(conn, doctor_id: str) -> Optional[dict]:
    return database.get_doctor(conn, doctor_id)

def get_equipment_state(conn, unit_id: str) -> Optional[dict]:
    return database.get_equipment_unit(conn, unit_id)

def get_incident_state(conn, incident_id: str) -> Optional[dict]:
    return database.get_incident(conn, incident_id)

def get_patient_state(conn, patient_id: str) -> Optional[dict]:
    return database.get_patient(conn, patient_id)