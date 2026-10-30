"""Human approval and the safe commit."""

from backend import database
from backend.hospital_state import is_state_current
from backend.schemas import ApprovalResult, ResourceBundle, ReservationResult

# =================================================================================
# OLD: Nurse-Only Approval (Preserved)
# =================================================================================

def _rejected(proposal_id: str, reason: str, nurse_id=None) -> ApprovalResult:
    return ApprovalResult(proposal_id=proposal_id, outcome="rejected", reason=reason, nurse_id=nurse_id)

def approve_proposal(conn, proposal_id: str, reviewer: str, reason: str = "") -> ApprovalResult:
    if not reviewer.strip():
        raise ValueError("Reviewer name is required.")

    with conn.transaction():
        proposal = database.get_proposal(conn, proposal_id, for_update=True)
        if proposal is None:
            return _rejected(proposal_id, "Proposal not found.")

        nurse_id = proposal["proposed_nurse_id"]

        if proposal["status"] != "pending_review":
            database.add_audit_event(conn, "approval_blocked", proposal_id, {"reviewer": reviewer, "reason": f"status is {proposal['status']}"})
            return _rejected(proposal_id, f"Proposal cannot be approved: status is {proposal['status']}.", nurse_id)

        saved_version = proposal["state_version_used"]
        if not proposal["validation_valid"] or saved_version is None:
            database.add_audit_event(conn, "approval_blocked", proposal_id, {"reviewer": reviewer, "reason": "proposal did not pass validation"})
            return _rejected(proposal_id, "Proposal did not pass validation.", nurse_id)

        new_version = database.mark_nurse_assigned(conn, nurse_id, saved_version)

        if new_version is None:
            nurse = database.get_nurse(conn, nurse_id)
            current_version = nurse["state_version"] if nurse else None
            if nurse is None:
                why = f"Nurse {nurse_id} no longer exists."
            elif not is_state_current(saved_version, current_version):
                why = f"State changed since validation (validated at version {saved_version}, now version {current_version})."
            else:
                why = f"Nurse {nurse_id} is no longer available."
            database.set_proposal_status(conn, proposal_id, "stale")
            database.add_audit_event(conn, "approval_failed_stale", proposal_id, {"reviewer": reviewer, "reason": why})
            return ApprovalResult(proposal_id=proposal_id, outcome="stale", reason=why, nurse_id=nurse_id)

        database.record_approval(conn, proposal_id, reviewer, "approved", reason)
        database.set_proposal_status(conn, proposal_id, "approved")
        database.add_audit_event(conn, "reviewer_approved", proposal_id, {"reviewer": reviewer})
        database.add_audit_event(conn, "assignment_committed", proposal_id, {"nurse_id": nurse_id, "new_state_version": new_version})
        
        return ApprovalResult(proposal_id=proposal_id, outcome="committed", reason=f"Nurse {nurse_id} assigned.", nurse_id=nurse_id, new_state_version=new_version)

def reject_proposal(conn, proposal_id: str, reviewer: str, reason: str = "") -> ApprovalResult:
    if not reviewer.strip():
        raise ValueError("Reviewer name is required.")

    with conn.transaction():
        proposal = database.get_proposal(conn, proposal_id, for_update=True)
        if proposal is None:
            return _rejected(proposal_id, "Proposal not found.")

        nurse_id = proposal["proposed_nurse_id"]
        if proposal["status"] != "pending_review":
            database.add_audit_event(conn, "rejection_blocked", proposal_id, {"reviewer": reviewer, "reason": f"status is {proposal['status']}"})
            return _rejected(proposal_id, f"Proposal cannot be rejected: status is {proposal['status']}.", nurse_id)

        database.record_approval(conn, proposal_id, reviewer, "rejected", reason)
        database.set_proposal_status(conn, proposal_id, "rejected_by_reviewer")
        database.add_audit_event(conn, "reviewer_rejected", proposal_id, {"reviewer": reviewer, "reason": reason})
        return _rejected(proposal_id, "Rejected by reviewer.", nurse_id)

# =================================================================================
# NEW: Atomic Bundle Reservation
# =================================================================================

def reserve_bundle(conn, bundle: ResourceBundle, reviewer: str, reason: str = "") -> ReservationResult:
    """Approves a validated bundle and atomically reserves ALL resources."""
    if not reviewer.strip():
        raise ValueError("Reviewer name is required.")

    with conn.transaction():
        # 1. Lock proposal to prevent double-clicking
        proposal = database.get_proposal(conn, bundle.proposal_id, for_update=True)
        if not proposal or proposal["status"] != "pending_review":
            return ReservationResult(outcome="rejected", reason="Proposal not found or already processed.")

        incident = database.get_incident(conn, bundle.incident_id)
        hospital_id = incident["hospital_id"]

        # 2. Create the Allocation header
        allocation_id = database.create_allocation(
            conn, hospital_id=hospital_id, incident_id=bundle.incident_id, 
            patient_id=bundle.patient_id, proposal_id=bundle.proposal_id
        )

        # 3. Conditionally reserve every resource. If ANY fail, the transaction raises and rolls back everything.
        for item in bundle.items:
            if item.resource_type == "bed":
                new_ver = database.mark_bed_reserved(conn, item.resource_id, item.state_version)
                if new_ver is None:
                    raise RuntimeError(f"Bed {item.resource_id} became unavailable (race condition).")
                database.add_allocation_item_bed(conn, allocation_id, hospital_id, item.resource_id)

            elif item.resource_type == "doctor":
                # Doctors don't have an 'available' boolean toggle for multi-patient workload,
                # but we bump their version if they are valid.
                new_ver = database.touch_doctor_version(conn, item.resource_id, item.state_version)
                if new_ver is None:
                    raise RuntimeError(f"Doctor {item.resource_id} became unavailable (race condition).")
                database.add_allocation_item_doctor(conn, allocation_id, hospital_id, item.resource_id)

            elif item.resource_type == "nurse":
                new_ver = database.mark_nurse_assigned(conn, item.resource_id, item.state_version)
                if new_ver is None:
                    raise RuntimeError(f"Nurse {item.resource_id} became unavailable (race condition).")
                database.add_allocation_item_nurse(conn, allocation_id, hospital_id, item.resource_id)

            elif item.resource_type == "equipment":
                new_ver = database.mark_equipment_reserved(conn, item.resource_id, item.state_version)
                if new_ver is None:
                    raise RuntimeError(f"Equipment {item.resource_id} became unavailable (race condition).")
                database.add_allocation_item_equipment(conn, allocation_id, hospital_id, item.resource_id)

        # 4. Finalize approval and audit
        database.record_approval(conn, bundle.proposal_id, reviewer, "approved", reason)
        database.set_proposal_status(conn, bundle.proposal_id, "approved")
        database.add_audit_event(conn, "bundle_reserved", bundle.proposal_id, {"allocation_id": allocation_id, "reviewer": reviewer})
        
        return ReservationResult(
            allocation_id=allocation_id, 
            outcome="committed", 
            reason="Bundle successfully reserved."
        )