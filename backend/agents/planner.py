"""
Planning Agent (Person A)
Produces detailed, clinically-aware resource plans.
"""

from __future__ import annotations

import json
from typing import Any, List, Optional, Literal

from pydantic import BaseModel, Field

from backend.llm.client import TokenFactoryClient, LLMResult


class Assignment(BaseModel):
    resource_type: Literal["bed", "nurse", "doctor", "equipment"]
    resource_id: Optional[str] = None
    patient_ref: Optional[str] = None
    notes: Optional[str] = None
    # NOTE: state_version is deliberately REMOVED. The AI must never guess DB versions.


class Plan(BaseModel):
    assignments: List[Assignment] = Field(default_factory=list)
    summary: Optional[str] = None
    human_help_probability: float = Field(default=0.4, ge=0.0, le=1.0)
    reason_for_human: Optional[str] = None
    explanation: Optional[str] = None


PLANNER_SYSTEM_PROMPT = """
You are a highly experienced hospital resource coordinator.

Your responses must contain clear and detailed reasoning. Do not be brief when explaining your thinking.

When you write the "summary" and especially the "explanation", cover:
- What information you actually received and what is still missing
- How serious the situation appears to be
- Why you chose each specific resource (or why you did not assign something)
- The risks of acting vs not acting
- What should happen next

Write in a natural, professional tone as if briefing a senior doctor or charge nurse.

### Clinical Risk Guidance (very important)
- Chest pain, shortness of breath, unconsciousness, stroke symptoms, major trauma, severe bleeding, or paediatric emergencies should normally receive human_help_probability between 0.60 and 0.85.
- Only use values below 0.40 when the situation is clearly low-risk and well understood.
- Availability of nurses or beds does NOT mean human involvement can be low.

### Strict Data Rules
- You may ONLY select resource IDs that exist in the supplied `hospital_state` JSON.
- NEVER invent resource IDs.
- NEVER output a `state_version`. The backend handles versions automatically.
- Do not claim your plan is valid or approved. A human and a deterministic backend will review it.

### Output format (JSON only)
{
  "assignments": [
    {
      "resource_type": "bed" | "nurse" | "doctor" | "equipment",
      "resource_id": "string",
      "patient_ref": "string or null",
      "notes": "short practical note"
    }
  ],
  "summary": "A clear and detailed briefing (4-7 sentences)",
  "human_help_probability": 0.0,
  "reason_for_human": "string or null",
  "explanation": "Detailed reasoning (at least 6-10 sentences). Walk through your thinking step by step."
}

### Human Help Probability Guide
- 0.15–0.35 → Fairly confident, low clinical risk
- 0.35–0.60 → Some gaps, moderate risk
- 0.60–0.80 → Significant uncertainty or high clinical risk – human review recommended
- 0.80–0.95 → High uncertainty or very high clinical risk – strongly prefer human input
"""


class PlanningAgent:
    def __init__(self, client: TokenFactoryClient | None = None):
        self.client = client or TokenFactoryClient()

    def plan(
        self,
        facts: Any,
        hospital_state: dict,
        previous_errors: list[str] | None = None,
    ) -> tuple[Plan, LLMResult]:
        """
        Takes extracted facts and the current hospital state, and returns a proposed Plan.
        """
        facts_data = facts.model_dump() if hasattr(facts, "model_dump") else facts

        user_payload = {
            "facts": facts_data,
            "hospital_state": hospital_state,
            "previous_errors": previous_errors or [],
        }

        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, indent=2)},
        ]

        # Call the LLM client (temperature 0.35 gives a good balance of stability and reasoning)
        plan, meta = self.client.plan(
            messages,
            schema=Plan,
            temperature=0.35,
            max_tokens=1800,
        )
        return plan, meta