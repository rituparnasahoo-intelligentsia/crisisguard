"""Shared data contracts (Pydantic models).

DRAFT: this file is shared with Person A and Person C. Confirm every field name
with them before treating it as final.
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field


# =================================================================================
# OLD: Nurse-Only Workflow (Preserved exactly for existing tests)
# =================================================================================

class ProposalInput(BaseModel):
    """What Person A's AI code sends us. It does NOT include a state version:
    any extra field such as "state_version" is ignored, because the backend
    reads the real version from the database itself."""

    proposal_id: str = Field(min_length=1)
    incident_description: str
    proposed_nurse_id: str


class ValidationResult(BaseModel):
    valid: bool
    reason: str
    nurse_id: str                       # the nurse ID the AI proposed, exactly as received
    state_version: Optional[int] = None  # None when the nurse does not exist


class ApprovalResult(BaseModel):
    proposal_id: str
    outcome: Literal["committed", "rejected", "stale"]
    reason: str
    nurse_id: Optional[str] = None
    new_state_version: Optional[int] = None  # only set when outcome == "committed"


# =================================================================================
# NEW: Hospital-Wide Triage and Bundles
# =================================================================================

class EmergencyReport(BaseModel):
    """What comes in from the field or the ER intake."""
    incident_id: str
    patient_id: str
    hospital_id: str
    reported_severity: Literal["low", "moderate", "high", "critical"]
    description: str


class TriageAssessment(BaseModel):
    """The output of the deterministic triage engine."""
    priority: Literal["P1", "P2", "P3", "P4"]
    reason: str
    requires_human_review: bool
    missing_information: bool = False


class ResourceItem(BaseModel):
    resource_type: Literal["bed", "doctor", "nurse", "equipment"]
    resource_id: str
    state_version: int


class ResourceBundle(BaseModel):
    """The proposed set of resources for a single patient."""
    proposal_id: str
    patient_id: str
    incident_id: str
    items: list[ResourceItem]
    explanation: str


class BundleValidationResult(BaseModel):
    valid: bool
    reason: str
    errors: list[str] = []
    warnings: list[str] = []


class ReservationResult(BaseModel):
    allocation_id: Optional[int] = None
    outcome: Literal["committed", "rejected", "stale"]
    reason: str