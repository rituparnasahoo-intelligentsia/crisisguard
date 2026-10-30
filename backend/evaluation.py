"""Seeded evaluation scenarios for the validator.

Runs entirely in memory against the three fictional seed nurses, so results are the
same every time and no database is touched. Run it with:

    python -m backend.evaluation

This checks the prototype's rules on fictional data. It is NOT a clinical validation.
"""

import sys

from backend.schemas import ProposalInput
from backend.validator import validate_against_record

# Must match backend/seed.sql (tests/test_scenarios.py checks that they agree).
SEED_NURSES = {
    "N01": {"nurse_id": "N01", "name": "Person A", "available": True,  "department": "Emergency", "state_version": 1},
    "N02": {"nurse_id": "N02", "name": "Person B", "available": False, "department": "ICU",       "state_version": 1},
    "N03": {"nurse_id": "N03", "name": "Person C", "available": True,  "department": "Emergency", "state_version": 1},
}

INCIDENT = "Fictional incident: simulated emergency in bay 2."

SCENARIOS = [
    {"name": "Available Person A",       "nurse_id": "N01", "expect_valid": True,  "expect_text": "exists and is available"},
    {"name": "Unavailable Person B",     "nurse_id": "N02", "expect_valid": False, "expect_text": "currently unavailable"},
    {"name": "Available Person C",       "nurse_id": "N03", "expect_valid": True,  "expect_text": "exists and is available"},
    {"name": "Nonexistent nurse N99",    "nurse_id": "N99", "expect_valid": False, "expect_text": "does not exist"},
    {"name": "Wrong case (n01)",         "nurse_id": "n01", "expect_valid": False, "expect_text": "does not exist"},
    {"name": "Blank nurse ID",           "nurse_id": "  ",  "expect_valid": False, "expect_text": "empty"},
]


def run_scenarios() -> list[dict]:
    """Run every scenario and return one result dict per scenario."""
    results = []
    for number, scenario in enumerate(SCENARIOS, start=1):
        proposal = ProposalInput(
            proposal_id=f"EVAL-{number}",
            incident_description=INCIDENT,
            proposed_nurse_id=scenario["nurse_id"],
        )
        outcome = validate_against_record(proposal, SEED_NURSES.get(scenario["nurse_id"]))
        passed = (outcome.valid == scenario["expect_valid"]
                  and scenario["expect_text"] in outcome.reason)
        results.append({"name": scenario["name"], "passed": passed,
                        "valid": outcome.valid, "reason": outcome.reason})
    return results


def main() -> int:
    results = run_scenarios()
    for r in results:
        print(f"[{'PASS' if r['passed'] else 'FAIL'}] {r['name']}: valid={r['valid']} - {r['reason']}")
    failed = sum(1 for r in results if not r["passed"])
    print(f"\n{len(results) - failed}/{len(results)} scenarios passed.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
