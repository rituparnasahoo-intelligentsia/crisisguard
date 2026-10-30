from __future__ import annotations

import logging
from typing import List, Optional

from pydantic import BaseModel, Field

from backend.llm.client import TokenFactoryClient, LLMResult

log = logging.getLogger("crisisguard.intake")


class Fact(BaseModel):
    field: str
    value: Optional[str] = None
    source_span: Optional[str] = None
    is_unknown: bool = False
    uncertainty: float = Field(default=0.5, ge=0.0, le=1.0)


class FactList(BaseModel):
    facts: List[Fact] = Field(default_factory=list)


INTAKE_SYSTEM_PROMPT = """
You are the Intake Agent for CrisisGuard AI — a hospital emergency resource coordination system.

Your only job is to extract clearly stated facts from the incident report.

### Output Rules
- Reply with ONLY a valid JSON object. No markdown, no explanations.
- Use exactly this structure:
{
  "facts": [
    {
      "field": "string",
      "value": "string or null",
      "source_span": "exact quote from the report or null",
      "is_unknown": true or false,
      "uncertainty": 0.0
    }
  ]
}

### Strict Extraction Rules
1. Only extract information that is explicitly written in the report.
2. source_span must be copied character-for-character from the original report.
3. If information is not clearly stated → value = null, source_span = null, is_unknown = true, uncertainty = 1.0.
4. NEVER guess or invent information.
5. Prefer short and precise source spans.

### Uncertainty Score (important)
- Never use exactly 0.0. Even clear statements have tiny uncertainty.
- 0.05 to 0.15 → Very clear and direct statement
- 0.16 to 0.35 → Clear but some minor ambiguity (e.g. "at least 7", "possibly more")
- 0.36 to 0.60 → Moderately uncertain or inferred from context
- 0.61 to 0.85 → Quite unclear
- 0.86 to 0.95 → Almost unknown
- 0.96 to 1.0  → Completely unknown / not mentioned

### Common fields (extract only if present)
location, time_of_incident, patients_total, patients_critical, chief_complaint,
symptoms, mechanism_of_injury, hazards, ambulance_eta, children_count,
known_medical_history, reports_pending, needs_further_investigation, reporting_source

Remember: Unknowns stay unknown. Never guess.
"""


class IntakeAgent:
    def __init__(self, client: TokenFactoryClient | None = None):
        self.client = client or TokenFactoryClient()

    def extract(self, report: str) -> tuple[FactList, LLMResult]:
        report = report.strip()
        if not report:
            log.warning("Empty report received")
            return FactList(facts=[]), LLMResult(text="", model="none", latency_ms=0.0)

        messages = [
            {"role": "system", "content": INTAKE_SYSTEM_PROMPT},
            {"role": "user", "content": report},
        ]

        log.info("Extracting facts (%d chars)", len(report))

        facts, meta = self.client.extract(
            messages,
            schema=FactList,
            temperature=0.0,
            max_tokens=1200,
        )

        facts = self._verify_source_spans(facts, report)

        log.info(
            "Intake done | facts=%d | unknown=%d | latency=%.0fms",
            len(facts.facts),
            sum(1 for f in facts.facts if f.is_unknown),
            meta.latency_ms,
        )
        return facts, meta

    def _verify_source_spans(self, facts: FactList, report: str) -> FactList:
        cleaned = []
        for fact in facts.facts:
            # If the AI hallucinated a quote that isn't in the report, wipe it out.
            if fact.source_span and fact.source_span not in report:
                log.warning("Bad source span for '%s'. Marking unknown.", fact.field)
                fact.value = None
                fact.source_span = None
                fact.is_unknown = True
                fact.uncertainty = max(0.05, fact.uncertainty)
            cleaned.append(fact)
        return FactList(facts=cleaned)