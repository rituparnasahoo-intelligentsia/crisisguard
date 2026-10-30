"""Deterministic Triage Engine.

Rules are explicit, configured demonstration rules. 
AI is not involved here. Missing information escalates to human review.

WARNING: These are DEMO placeholders, not medically validated clinical rules.
"""

from backend.schemas import EmergencyReport, TriageAssessment

def assess_priority(report: EmergencyReport) -> TriageAssessment:
    """Map explicit demonstration rules to a priority level."""
    
    # Rule 1: Missing or uncertain info never defaults to low priority.
    if not report.description.strip() or not report.reported_severity:
        return TriageAssessment(
            priority="P2",
            reason="Missing clinical description or severity. Escalating for human review.",
            requires_human_review=True,
            missing_information=True
        )

    # Rule 2: Explicit critical or high severity.
    if report.reported_severity == "critical":
        return TriageAssessment(
            priority="P1",
            reason="Reported severity is critical.",
            requires_human_review=False
        )
    
    if report.reported_severity == "high":
        return TriageAssessment(
            priority="P2",
            reason="Reported severity is high.",
            requires_human_review=False
        )
        
    if report.reported_severity == "moderate":
        return TriageAssessment(
            priority="P3",
            reason="Reported severity is moderate.",
            requires_human_review=False
        )
    
    if report.reported_severity == "low":
        return TriageAssessment(
            priority="P4",
            reason="Reported severity is low.",
            requires_human_review=False
        )
        
    # Fallback if severity string is somehow unexpected
    return TriageAssessment(
        priority="P2",
        reason="Unrecognized severity. Escalating for human review.",
        requires_human_review=True
    )