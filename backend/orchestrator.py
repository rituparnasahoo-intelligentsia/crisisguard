from __future__ import annotations
import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional
from backend.agents.intake import IntakeAgent, FactList
from backend.agents.planner import PlanningAgent, Plan
from backend.llm.client import TokenFactoryClient
from backend.schemas import ResourceItem, ResourceBundle, BundleValidationResult

log = logging.getLogger("crisisguard.orchestrator")

@dataclass
class PipelineResult:
    facts: Optional[FactList] = None
    plan: Optional[Plan] = None
    bundle: Optional[ResourceBundle] = None
    validation: Optional[BundleValidationResult] = None
    errors: list[str] = field(default_factory=list)
    escalated_probability: float = 0.0
    attempts: int = 0
    summary: Optional[str] = None
    human_help_probability: float = 0.0
    overall_confidence: float = 0.5
    
    @property
    def escalated(self) -> bool:
        # Force escalation if validation failed or AI wants a human
        return (
            self.bundle is None 
            or self.validation is None 
            or not self.validation.valid 
            or self.human_help_probability >= 0.75
        )

class Orchestrator:
    def __init__(self, client: TokenFactoryClient | None = None, max_retries: int = 3):
        self.client = client or TokenFactoryClient()
        self.intake = IntakeAgent(self.client)
        self.planner = PlanningAgent(self.client)
        self.max_retries = max_retries

    def run(self, report: str, hospital_state: dict, *, incident_id: str = "inc_demo", patient_id: str = "pat_demo", validator_func=None) -> PipelineResult:
        log.info("Pipeline started")

        facts, _ = self.intake.extract(report)
        overall_confidence = self._calculate_confidence(facts)
        errors: list[str] = []

        for attempt in range(1, self.max_retries + 1):
            plan, _ = self.planner.plan(facts=facts, hospital_state=hospital_state, previous_errors=errors if errors else None)
            human_help = plan.human_help_probability

            # Build Bundle using the BACKEND's real versions
            bundle, build_errors = self._build_bundle(plan, incident_id, patient_id, hospital_state)
            
            if build_errors:
                errors = build_errors
                continue

            if not bundle.items:
                errors = ["Planning Agent produced no usable resources."]
                continue

            if validator_func is None:
                validation = BundleValidationResult(valid=False, reason="Validation unavailable.")
            else:
                validation = validator_func(bundle)

            if validation.valid:
                return PipelineResult(
                    facts=facts, plan=plan, bundle=bundle, validation=validation,
                    errors=[], escalated_probability=round(human_help, 2),
                    attempts=attempt, summary=plan.summary or plan.explanation,
                    human_help_probability=human_help, overall_confidence=overall_confidence
                )

            errors = validation.errors or [validation.reason]

        # Retries exhausted
        return PipelineResult(
            facts=facts, plan=plan, bundle=bundle, validation=validation, errors=errors,
            escalated_probability=0.95, attempts=self.max_retries,
            summary="High uncertainty or repeated validation failures. Human review required.",
            human_help_probability=plan.human_help_probability if plan else 0.85,
            overall_confidence=overall_confidence
        )

    def _build_bundle(self, plan: Plan, incident_id: str, patient_id: str, hospital_state: dict) -> tuple[ResourceBundle, list[str]]:
        items = []
        errors = []
        seen = set()
        
        collections = {
            "bed": hospital_state.get("beds", []),
            "doctor": hospital_state.get("doctors", []),
            "nurse": hospital_state.get("nurses", []),
            "equipment": hospital_state.get("equipment", []),
        }

        for a in plan.assignments:
            if not a.resource_id or a.resource_type not in collections:
                continue
                
            key = (a.resource_type, a.resource_id)
            if key in seen:
                errors.append(f"Duplicate assignment: {a.resource_id}")
                continue
            seen.add(key)

            # Look up the real state_version from the DB snapshot
            id_field = {"bed": "bed_id", "doctor": "doctor_id", "nurse": "nurse_id", "equipment": "unit_id"}[a.resource_type]
            record = next((r for r in collections[a.resource_type] if r.get(id_field) == a.resource_id), None)

            if not record:
                errors.append(f"{a.resource_type} {a.resource_id} not found in DB snapshot.")
                continue

            items.append(ResourceItem(
                resource_type=a.resource_type,
                resource_id=a.resource_id,
                state_version=record["state_version"] # Use real DB version
            ))

        return ResourceBundle(
            proposal_id=f"bundle_{uuid.uuid4().hex[:8]}",
            patient_id=patient_id, incident_id=incident_id, items=items,
            explanation=plan.explanation or plan.summary or "AI-generated resource bundle"
        ), errors

    def _calculate_confidence(self, facts: FactList) -> float:
        if not facts.facts: return 0.2
        unknown_ratio = sum(1 for f in facts.facts if f.is_unknown) / len(facts.facts)
        avg_uncertainty = sum(f.uncertainty for f in facts.facts) / len(facts.facts)
        return round(max(0.1, min(0.95, 1.0 - (0.6 * unknown_ratio + 0.4 * avg_uncertainty))), 2)