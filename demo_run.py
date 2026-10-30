"""End-to-End Demo Script.
Simulates an emergency, runs triage, validates resources, reserves them, and exports to CSV.
"""
import csv
from backend.database import get_connection
from backend.schemas import EmergencyReport, ResourceBundle, ResourceItem
from backend.triage import assess_priority
from backend.validator import validate_bundle
from backend.approval import reserve_bundle

def run_demo():
    with get_connection() as conn:
        print("--- 1. EMERGENCY REPORT ARRIVES ---")
        report = EmergencyReport(
            incident_id="INC-001", 
            patient_id="PT-001", 
            hospital_id="H01",
            reported_severity="critical",
            description="Patient arrived with severe chest pain."
        )
        print(f"Incident: {report.incident_id} | Severity: {report.reported_severity}")

        print("\n--- 2. TRIAGE ENGINE ---")
        triage = assess_priority(report)
        print(f"Priority: {triage.priority}")
        print(f"Reason: {triage.reason}")
        print(f"Requires Human Review: {triage.requires_human_review}")

        print("\n--- 3. AI PROPOSES A RESOURCE BUNDLE ---")
        # We use real IDs from your seed.sql
        bundle = ResourceBundle(
            proposal_id="DEMO-BUNDLE-01",
            patient_id="PT-001",
            incident_id="INC-001",
            explanation="Critical patient needs ICU bed, doctor, nurse, and ventilator.",
            items=[
                ResourceItem(resource_type="bed", resource_id="B-H01-ICU-01", state_version=1),
                ResourceItem(resource_type="doctor", resource_id="D02", state_version=1),
                ResourceItem(resource_type="nurse", resource_id="N02", state_version=1), # Note: N02 is seeded as False, so this will fail validation
                ResourceItem(resource_type="equipment", resource_id="VENT-H01-01", state_version=1)
            ]
        )
        print(f"Proposed: 1 Bed, 1 Doctor, 1 Nurse, 1 Ventilator")

        print("\n--- 4. DETERMINISTIC VALIDATOR ---")
        validation = validate_bundle(conn, bundle)
        print(f"Valid: {validation.valid}")
        if not validation.valid:
            for error in validation.errors:
                print(f"  - Error: {error}")
            print("\n!!! Bundle rejected by validator. Halting demo. !!!")
            # We will fix the nurse in the script so the demo can continue
            print("\n(Self-Correction: Changing Nurse to N01 who is available)")
            bundle.items[2].resource_id = "N01"
            validation = validate_bundle(conn, bundle)
            print(f"Valid after correction: {validation.valid}")

        print("\n--- 5. HUMAN APPROVAL & ATOMIC RESERVATION ---")
        if validation.valid:
            # We need to save the proposal to the DB first so it can be approved
            conn.execute("""
                INSERT INTO proposals (proposal_id, incident_description, validation_valid, validation_reason, status, proposal_kind, incident_id, patient_id)
                VALUES ('DEMO-BUNDLE-01', 'Demo bundle', TRUE, 'Validated', 'pending_review', 'bundle', 'INC-001', 'PT-001')
                ON CONFLICT DO NOTHING;
            """)
            
            result = reserve_bundle(conn, bundle, reviewer="Dr. Admin", reason="Life-saving intervention")
            print(f"Reservation Outcome: {result.outcome}")
            print(f"Reason: {result.reason}")
            if result.allocation_id:
                print(f"Allocation ID: {result.allocation_id}")

        print("\n--- 6. EXPORTING TO CSV ---")
        export_to_csv(conn, "crisisguard_output.csv")

def export_to_csv(conn, filename):
    # We query a JOIN to see exactly what was allocated to the patient
    query = """
        SELECT 
            a.allocation_id,
            a.patient_id,
            p.display_name AS patient_name,
            a.incident_id,
            ai.resource_type,
            COALESCE(ai.bed_id, ai.doctor_id, ai.nurse_id, ai.equipment_unit_id) AS resource_id
        FROM allocations a
        JOIN patients p ON a.patient_id = p.patient_id
        JOIN allocation_items ai ON a.allocation_id = ai.allocation_id
        ORDER BY a.allocation_id, ai.resource_type;
    """
    rows = conn.execute(query).fetchall()
    
    if not rows:
        print("No allocations found in database.")
        return

    with open(filename, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        # Write headers
        writer.writerow(["Allocation ID", "Patient ID", "Patient Name", "Incident ID", "Resource Type", "Resource ID"])
        # Write data
        for row in rows:
            writer.writerow([
                row["allocation_id"], 
                row["patient_id"], 
                row["patient_name"], 
                row["incident_id"], 
                row["resource_type"], 
                row["resource_id"]
            ])
    print(f"Success! Open '{filename}' in Excel or VS Code to see the output.")

if __name__ == "__main__":
    run_demo()