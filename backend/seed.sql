-- Seed data: FICTIONAL hospitals, staff, beds, equipment, patients and incidents.
-- No real people, hospitals or patient information. Run AFTER the migrations.
-- Every insert uses ON CONFLICT DO NOTHING, so running this again never overwrites
-- or resets rows that already exist (use scripts.reset_demo for a deliberate reset).

INSERT INTO hospitals (hospital_id, name, city, latitude, longitude, operational_status, max_concurrent_patients) VALUES
    ('H01', 'Riverside General (fictional)',  'Northport', 20.10000, 85.10000, 'operational', 12),
    ('H02', 'Hillcrest Medical (fictional)',  'Eastvale',  20.20000, 85.30000, 'operational',  8)
ON CONFLICT (hospital_id) DO NOTHING;

INSERT INTO wards (ward_id, hospital_id, name, ward_type, location_note, capacity, status) VALUES
    ('W-H01-ED',  'H01', 'Emergency Department', 'emergency', 'Ground floor', 6, 'open'),
    ('W-H01-ICU', 'H01', 'Intensive Care Unit',  'icu',       'Second floor', 3, 'open'),
    ('W-H01-GEN', 'H01', 'General Ward',         'general',   'First floor',  6, 'open'),
    ('W-H02-ED',  'H02', 'Emergency Department', 'emergency', 'Ground floor', 4, 'open'),
    ('W-H02-ICU', 'H02', 'Intensive Care Unit',  'icu',       'Second floor', 2, 'open'),
    ('W-H02-GEN', 'H02', 'General Ward',         'general',   'First floor',  4, 'open')
ON CONFLICT (ward_id) DO NOTHING;

-- Nurses N01-N03 are the original three demo nurses (now in hospital H01).
INSERT INTO nurses (nurse_id, name, available, department, state_version, hospital_id, shift) VALUES
    ('N01', 'Person A', TRUE,  'Emergency', 1, 'H01', 'day'),
    ('N02', 'Person B', FALSE, 'ICU',       1, 'H01', 'day'),
    ('N03', 'Person C', TRUE,  'Emergency', 1, 'H01', 'day'),
    ('N04', 'Person D', TRUE,  'Emergency', 1, 'H02', 'day'),
    ('N05', 'Person E', TRUE,  'ICU',       1, 'H02', 'night'),
    ('N06', 'Person F', FALSE, 'General',   1, 'H02', 'day')
ON CONFLICT (nurse_id) DO NOTHING;

INSERT INTO doctors (doctor_id, name, hospital_id, department, specialization, shift, available) VALUES
    ('D01', 'Doctor A', 'H01', 'Emergency', 'Emergency Medicine', 'day',     TRUE),
    ('D02', 'Doctor B', 'H01', 'ICU',       'Critical Care',      'day',     TRUE),
    ('D03', 'Doctor C', 'H01', 'General',   'Internal Medicine',  'evening', FALSE),
    ('D04', 'Doctor D', 'H02', 'Emergency', 'Emergency Medicine', 'day',     TRUE),
    ('D05', 'Doctor E', 'H02', 'ICU',       'Critical Care',      'night',   TRUE),
    ('D06', 'Doctor F', 'H02', 'General',   'Cardiology',         'day',     TRUE)
ON CONFLICT (doctor_id) DO NOTHING;

-- One bed per ward slot (25 beds). B-H01-ED-06 is out of service and B-H02-GEN-04
-- is being cleaned, so not every bed is free in the demo.
INSERT INTO beds (bed_id, hospital_id, ward_id, bed_type, status)
SELECT 'B-' || w.code || '-' || lpad(n::text, 2, '0'),
       w.hospital_id, w.ward_id, w.ward_type,
       CASE 'B-' || w.code || '-' || lpad(n::text, 2, '0')
            WHEN 'B-H01-ED-06'  THEN 'out_of_service'
            WHEN 'B-H02-GEN-04' THEN 'cleaning'
            ELSE 'free'
       END
FROM (VALUES
        ('H01', 'W-H01-ED',  'emergency', 'H01-ED',  6),
        ('H01', 'W-H01-ICU', 'icu',       'H01-ICU', 3),
        ('H01', 'W-H01-GEN', 'general',   'H01-GEN', 6),
        ('H02', 'W-H02-ED',  'emergency', 'H02-ED',  4),
        ('H02', 'W-H02-ICU', 'icu',       'H02-ICU', 2),
        ('H02', 'W-H02-GEN', 'general',   'H02-GEN', 4)
     ) AS w(hospital_id, ward_id, ward_type, code, bed_count)
CROSS JOIN LATERAL generate_series(1, w.bed_count) AS n
ON CONFLICT (bed_id) DO NOTHING;

INSERT INTO equipment_types (type_id, name) VALUES
    ('ventilator',      'Ventilator'),
    ('defibrillator',   'Defibrillator'),
    ('cardiac_monitor', 'Cardiac monitor'),
    ('infusion_pump',   'Infusion pump')
ON CONFLICT (type_id) DO NOTHING;

INSERT INTO equipment_units (unit_id, type_id, hospital_id, ward_id, status, maintenance_due_date) VALUES
    ('VENT-H01-01', 'ventilator',      'H01', 'W-H01-ICU', 'available',   NULL),
    ('VENT-H01-02', 'ventilator',      'H01', 'W-H01-ICU', 'maintenance', DATE '2026-11-15'),
    ('DEFIB-H01-01','defibrillator',   'H01', 'W-H01-ED',  'available',   NULL),
    ('MON-H01-01',  'cardiac_monitor', 'H01', 'W-H01-ED',  'available',   NULL),
    ('MON-H01-02',  'cardiac_monitor', 'H01', 'W-H01-ICU', 'available',   NULL),
    ('VENT-H02-01', 'ventilator',      'H02', 'W-H02-ICU', 'available',   NULL),
    ('DEFIB-H02-01','defibrillator',   'H02', 'W-H02-ED',  'available',   NULL),
    ('MON-H02-01',  'cardiac_monitor', 'H02', 'W-H02-ED',  'available',   NULL)
ON CONFLICT (unit_id) DO NOTHING;

INSERT INTO patients (patient_id, display_name, age_years) VALUES
    ('PT-001', 'Patient One (fictional)',   34),
    ('PT-002', 'Patient Two (fictional)',   67),
    ('PT-003', 'Patient Three (fictional)',  8)
ON CONFLICT (patient_id) DO NOTHING;

INSERT INTO incidents (incident_id, hospital_id, emergency_type, reported_severity, arrival_time, status, description) VALUES
    ('INC-001', 'H01', 'road_traffic_collision', 'critical', TIMESTAMPTZ '2026-10-25 20:00:00+05:30', 'reported',
        'Fictional drill: two patients arrive after a simulated vehicle collision.'),
    ('INC-002', 'H01', 'chest_pain',             'high',     TIMESTAMPTZ '2026-10-25 20:05:00+05:30', 'reported',
        'Fictional drill: one patient arrives with simulated chest pain.')
ON CONFLICT (incident_id) DO NOTHING;

INSERT INTO incident_patients (incident_id, patient_id, reported_condition) VALUES
    ('INC-001', 'PT-001', 'Reported injuries after collision (simulated)'),
    ('INC-001', 'PT-002', 'Reported injuries after collision (simulated)'),
    ('INC-002', 'PT-003', 'Reported chest pain (simulated)')
ON CONFLICT (incident_id, patient_id) DO NOTHING;

-- Configurable constraints for the validator. These are DEMO placeholder values, not clinical guidance.
INSERT INTO policy_settings (key, value, description) VALUES
    ('max_active_patients_per_nurse',  '{"value": 4}',
     'Demo workload limit: active patients one nurse may serve at once.'),
    ('max_active_patients_per_doctor', '{"value": 6}',
     'Demo workload limit: active patients one doctor may serve at once.'),
    ('icu_requires_reported_severity', '{"values": ["critical"]}',
     'DEMO PLACEHOLDER ONLY: reported severities allowed an ICU bed proposal. Real clinical policy must come from qualified clinicians.')
ON CONFLICT (key) DO NOTHING;
