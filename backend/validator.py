"""Deterministic validator: plain Python rules, no AI involved.
"""

from typing import Optional
from backend import database, hospital_state
from backend.schemas import ProposalInput, ValidationResult, ResourceBundle, BundleValidationResult

# =================================================================================
# OLD: Nurse-Only Validator (Preserved)
# =================================================================================

def validate_against_record(proposal: ProposalInput, nurse: Optional[dict]) -> ValidationResult:
    """Decide whether a proposal is valid, given the nurse record (or None if no such nurse)."""
    nurse_id = proposal.proposed_nurse_id

    if not nurse_id.strip():
        return ValidationResult(valid=False, reason="Proposed nurse ID is empty.", nurse_id=nurse_id)
    if not proposal.incident_description.strip():
        return ValidationResult(valid=False, reason="Incident description is empty.", nurse_id=nurse_id)

    if nurse is None:
        return ValidationResult(valid=False, reason=f"Nurse {nurse_id} does not exist.", nurse_id=nurse_id)

    if not nurse["available"]:
        return ValidationResult(
            valid=False,
            reason=f"Nurse {nurse_id} exists but is currently unavailable.",
            nurse_id=nurse_id,
            state_version=nurse["state_version"],
        )

    return ValidationResult(
        valid=True,
        reason=f"Nurse {nurse_id} exists and is available.",
        nurse_id=nurse_id,
        state_version=nurse["state_version"],
    )

def validate_proposal(conn, proposal: ProposalInput) -> ValidationResult:
    nurse = hospital_state.get_nurse_state(conn, proposal.proposed_nurse_id)
    return validate_against_record(proposal, nurse)

def validate_and_save_proposal(conn, proposal: ProposalInput) -> ValidationResult:
    if database.get_proposal(conn, proposal.proposal_id) is not None:
        raise ValueError(f"Proposal {proposal.proposal_id} already exists.")

    result = validate_proposal(conn, proposal)
    status = "pending_review" if result.valid else "rejected_by_validator"

    with conn.transaction():
        database.save_proposal(
            conn, proposal_id=proposal.proposal_id,
            incident_description=proposal.incident_description,
            proposed_nurse_id=proposal.proposed_nurse_id,
            valid=result.valid, reason=result.reason,
            state_version_used=result.state_version if result.valid else None,
            status=status,
        )
        database.add_audit_event(conn, "proposal_created", proposal.proposal_id, {"nurse_id": proposal.proposed_nurse_id})
        database.add_audit_event(conn, "validation_passed" if result.valid else "validation_failed", proposal.proposal_id, {"reason": result.reason})
    return result

# =================================================================================
# NEW: Bundle Validator
# =================================================================================

def validate_bundle(conn, bundle: ResourceBundle) -> BundleValidationResult:
    """Checks a multi-resource bundle against the current DB state."""
    errors = []
    warnings = []

    incident = database.get_incident(conn, bundle.incident_id)
    if not incident:
        errors.append(f"Incident {bundle.incident_id} does not exist.")
        return BundleValidationResult(valid=False, reason="Incident missing.", errors=errors)

    hospital_id = incident["hospital_id"]
    
    for item in bundle.items:
        # 1. Bed Check
        if item.resource_type == "bed":
            bed = database.get_bed(conn, item.resource_id)
            if not bed:
                errors.append(f"Bed {item.resource_id} does not exist.")
            elif bed["hospital_id"] != hospital_id:
                errors.append(f"Bed {item.resource_id} is in a different hospital.")
            elif bed["status"] != "free":
                errors.append(f"Bed {item.resource_id} is not free (status: {bed['status']}).")
            elif bed["state_version"] != item.state_version:
                errors.append(f"Bed {item.resource_id} changed since planning (stale).")

        # 2. Doctor Check
        elif item.resource_type == "doctor":
            doc = database.get_doctor(conn, item.resource_id)
            if not doc:
                errors.append(f"Doctor {item.resource_id} does not exist.")
            elif doc["hospital_id"] != hospital_id:
                errors.append(f"Doctor {item.resource_id} is in a different hospital.")
            elif not doc["available"]:
                errors.append(f"Doctor {item.resource_id} is unavailable.")
            elif doc["state_version"] != item.state_version:
                errors.append(f"Doctor {item.resource_id} changed since planning (stale).")

        # 3. Nurse Check
        elif item.resource_type == "nurse":
            nurse = database.get_nurse(conn, item.resource_id)
            if not nurse:
                errors.append(f"Nurse {item.resource_id} does not exist.")
            # Nurses table doesn't have hospital_id in the old schema, but it does in the DB
            elif not nurse["available"]:
                errors.append(f"Nurse {item.resource_id} is unavailable.")
            elif nurse["state_version"] != item.state_version:
                errors.append(f"Nurse {item.resource_id} changed since planning (stale).")

        # 4. Equipment Check
        elif item.resource_type == "equipment":
            eq = database.get_equipment_unit(conn, item.resource_id)
            if not eq:
                errors.append(f"Equipment {item.resource_id} does not exist.")
            elif eq["hospital_id"] != hospital_id:
                errors.append(f"Equipment {item.resource_id} is in a different hospital.")
            elif eq["status"] != "available":
                errors.append(f"Equipment {item.resource_id} is not available (status: {eq['status']}).")
            elif eq["state_version"] != item.state_version:
                errors.append(f"Equipment {item.resource_id} changed since planning (stale).")

    if errors:
        return BundleValidationResult(valid=False, reason="One or more resources failed validation.", errors=errors, warnings=warnings)
    
    return BundleValidationResult(valid=True, reason="All bundle resources are available and unchanged.", errors=[], warnings=warnings)