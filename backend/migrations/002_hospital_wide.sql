-- Migration 002: hospital-wide resource model (fictional data only).
-- Evolves the nurse-only schema WITHOUT breaking it: old columns stay, old rows are kept,
-- and the existing nurse-only workflow and its tests keep working.
--
-- Design rules used throughout:
--   * Every resource row that can be reserved has a state_version (optimistic concurrency).
--   * "Belongs to the correct hospital" is enforced by the database through composite
--     foreign keys (resource_id, hospital_id), not only by Python.
--   * AI-supplied IDs (proposal_items.resource_id) have NO foreign key, so invalid
--     AI suggestions can still be stored and audited.
--   * Exclusive resources (beds, equipment units) are protected by partial unique indexes:
--     the database itself refuses two active allocations of the same bed.

-- ============================================================ organisation

CREATE TABLE hospitals (
    hospital_id             TEXT PRIMARY KEY,
    name                    TEXT NOT NULL,
    city                    TEXT NOT NULL,
    latitude                NUMERIC(8,5) CHECK (latitude  BETWEEN -90  AND 90),
    longitude               NUMERIC(8,5) CHECK (longitude BETWEEN -180 AND 180),
    operational_status      TEXT NOT NULL DEFAULT 'operational'
                            CHECK (operational_status IN ('operational', 'diverting', 'closed')),
    -- Configured operating cap on simultaneously active patients (a policy number,
    -- separate from the physical bed count).
    max_concurrent_patients INTEGER NOT NULL CHECK (max_concurrent_patients >= 0),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE wards (
    ward_id       TEXT PRIMARY KEY,
    hospital_id   TEXT NOT NULL REFERENCES hospitals (hospital_id),
    name          TEXT NOT NULL,
    ward_type     TEXT NOT NULL CHECK (ward_type IN ('emergency', 'icu', 'general')),
    location_note TEXT NOT NULL DEFAULT '',
    capacity      INTEGER NOT NULL CHECK (capacity > 0),
    status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
    -- Target for composite foreign keys ("this ward belongs to this hospital").
    UNIQUE (ward_id, hospital_id)
);

-- ============================================================ staff

-- Existing table: add the hospital and shift. Rows from the old demo (if any) are
-- backfilled into hospital H01 so the new NOT NULL rule can be applied safely.
ALTER TABLE nurses ADD COLUMN hospital_id TEXT;
ALTER TABLE nurses ADD COLUMN shift TEXT NOT NULL DEFAULT 'day'
    CHECK (shift IN ('day', 'evening', 'night'));

INSERT INTO hospitals (hospital_id, name, city, max_concurrent_patients)
SELECT 'H01', 'Riverside General (fictional)', 'Northport', 12
WHERE EXISTS (SELECT 1 FROM nurses)
ON CONFLICT (hospital_id) DO NOTHING;

UPDATE nurses SET hospital_id = 'H01' WHERE hospital_id IS NULL;

ALTER TABLE nurses ALTER COLUMN hospital_id SET NOT NULL;
ALTER TABLE nurses ADD CONSTRAINT nurses_hospital_fk
    FOREIGN KEY (hospital_id) REFERENCES hospitals (hospital_id);
ALTER TABLE nurses ADD CONSTRAINT nurses_id_hospital_key UNIQUE (nurse_id, hospital_id);

CREATE TABLE doctors (
    doctor_id      TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    hospital_id    TEXT NOT NULL REFERENCES hospitals (hospital_id),
    department     TEXT NOT NULL,
    specialization TEXT NOT NULL,
    shift          TEXT NOT NULL CHECK (shift IN ('day', 'evening', 'night')),
    available      BOOLEAN NOT NULL,
    state_version  INTEGER NOT NULL DEFAULT 1 CHECK (state_version >= 1),
    UNIQUE (doctor_id, hospital_id)
);

-- ============================================================ beds and equipment

-- Cleaning is part of status ('cleaning') so there is no second column that could
-- contradict it. A bed can only be reserved when its status is 'free'.
CREATE TABLE beds (
    bed_id        TEXT PRIMARY KEY,
    hospital_id   TEXT NOT NULL,
    ward_id       TEXT NOT NULL,
    bed_type      TEXT NOT NULL CHECK (bed_type IN ('emergency', 'icu', 'general')),
    status        TEXT NOT NULL DEFAULT 'free'
                  CHECK (status IN ('free', 'reserved', 'occupied', 'cleaning', 'out_of_service')),
    state_version INTEGER NOT NULL DEFAULT 1 CHECK (state_version >= 1),
    FOREIGN KEY (ward_id, hospital_id) REFERENCES wards (ward_id, hospital_id),
    UNIQUE (bed_id, hospital_id)
);

CREATE TABLE equipment_types (
    type_id TEXT PRIMARY KEY,
    name    TEXT NOT NULL
);

-- Each physical unit is tracked individually (its own status, maintenance date, version).
CREATE TABLE equipment_units (
    unit_id              TEXT PRIMARY KEY,
    type_id              TEXT NOT NULL REFERENCES equipment_types (type_id),
    hospital_id          TEXT NOT NULL REFERENCES hospitals (hospital_id),
    ward_id              TEXT,   -- NULL = stored centrally, not in a ward
    status               TEXT NOT NULL DEFAULT 'available'
                         CHECK (status IN ('available', 'reserved', 'in_use', 'maintenance', 'out_of_service')),
    maintenance_due_date DATE,
    state_version        INTEGER NOT NULL DEFAULT 1 CHECK (state_version >= 1),
    FOREIGN KEY (ward_id, hospital_id) REFERENCES wards (ward_id, hospital_id),
    UNIQUE (unit_id, hospital_id)
);

-- Trigger: a ward cannot hold more beds than its capacity, and a bed's type must
-- match its ward's type. Locking the ward row serialises two simultaneous bed inserts.
CREATE FUNCTION enforce_ward_rules() RETURNS trigger AS $$
DECLARE
    ward_capacity INTEGER;
    ward_kind     TEXT;
    bed_count     INTEGER;
BEGIN
    SELECT capacity, ward_type INTO ward_capacity, ward_kind
      FROM wards WHERE ward_id = NEW.ward_id FOR UPDATE;

    IF ward_kind <> NEW.bed_type THEN
        RAISE EXCEPTION 'Bed type % does not match ward type % for ward %',
            NEW.bed_type, ward_kind, NEW.ward_id;
    END IF;

    SELECT count(*) INTO bed_count FROM beds
     WHERE ward_id = NEW.ward_id AND bed_id <> NEW.bed_id;
    IF bed_count >= ward_capacity THEN
        RAISE EXCEPTION 'Ward % is at capacity (%)', NEW.ward_id, ward_capacity;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER beds_enforce_ward_rules
    BEFORE INSERT OR UPDATE OF ward_id, bed_type ON beds
    FOR EACH ROW EXECUTE FUNCTION enforce_ward_rules();

-- ============================================================ patients and incidents

-- is_fictional can only be TRUE: the database refuses non-fictional patient rows.
CREATE TABLE patients (
    patient_id   TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    age_years    INTEGER CHECK (age_years BETWEEN 0 AND 120),
    is_fictional BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT patients_must_be_fictional CHECK (is_fictional)
);

CREATE TABLE incidents (
    incident_id       TEXT PRIMARY KEY,
    hospital_id       TEXT NOT NULL REFERENCES hospitals (hospital_id),
    emergency_type    TEXT NOT NULL,
    reported_severity TEXT NOT NULL CHECK (reported_severity IN ('low', 'moderate', 'high', 'critical')),
    arrival_time      TIMESTAMPTZ NOT NULL,
    status            TEXT NOT NULL DEFAULT 'reported'
                      CHECK (status IN ('reported', 'extracted', 'planned', 'pending_review',
                                        'allocated', 'closed', 'cancelled')),
    description       TEXT NOT NULL,
    extraction        JSONB,   -- Agent A output (kept as evidence; untrusted until validated)
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (incident_id, hospital_id)
);

-- Which patients belong to which incident (many-to-many).
CREATE TABLE incident_patients (
    incident_id        TEXT NOT NULL REFERENCES incidents (incident_id),
    patient_id         TEXT NOT NULL REFERENCES patients (patient_id),
    reported_condition TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (incident_id, patient_id)
);

-- ============================================================ users and policy

-- Password hashes are added in the authentication phase; no users are seeded yet.
CREATE TABLE app_users (
    user_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE CHECK (length(trim(username)) > 0),
    role          TEXT NOT NULL CHECK (role IN ('administrator', 'reviewer')),
    password_hash TEXT NOT NULL,
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Explicit, configurable constraints read by the validator (workload limits etc.).
CREATE TABLE policy_settings (
    key         TEXT PRIMARY KEY,
    value       JSONB NOT NULL,
    description TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================ proposals (extended)

ALTER TABLE proposals ADD COLUMN proposal_kind TEXT NOT NULL DEFAULT 'nurse_only'
    CHECK (proposal_kind IN ('nurse_only', 'bundle'));
ALTER TABLE proposals ADD COLUMN incident_id         TEXT REFERENCES incidents (incident_id);
ALTER TABLE proposals ADD COLUMN patient_id          TEXT REFERENCES patients (patient_id);
ALTER TABLE proposals ADD COLUMN parent_proposal_id  TEXT REFERENCES proposals (proposal_id);
ALTER TABLE proposals ADD COLUMN plan_label          TEXT NOT NULL DEFAULT 'preferred';
ALTER TABLE proposals ADD COLUMN explanation         TEXT NOT NULL DEFAULT '';
ALTER TABLE proposals ADD COLUMN input_snapshot      JSONB;
ALTER TABLE proposals ADD COLUMN unmet_requirements  JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE proposals ADD COLUMN validation_errors   JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE proposals ADD COLUMN validation_warnings JSONB NOT NULL DEFAULT '[]'::jsonb;

-- Bundle proposals name several resources (see proposal_items), not one nurse.
ALTER TABLE proposals ALTER COLUMN proposed_nurse_id DROP NOT NULL;
ALTER TABLE proposals ADD CONSTRAINT nurse_only_needs_nurse
    CHECK (proposal_kind <> 'nurse_only' OR proposed_nurse_id IS NOT NULL);
ALTER TABLE proposals ADD CONSTRAINT bundle_needs_incident_and_patient
    CHECK (proposal_kind <> 'bundle' OR (incident_id IS NOT NULL AND patient_id IS NOT NULL));

-- Bundle versions live per item, so the single-version rule applies to nurse-only proposals.
ALTER TABLE proposals DROP CONSTRAINT valid_proposals_have_version;
ALTER TABLE proposals ADD CONSTRAINT valid_proposals_have_version
    CHECK (NOT validation_valid OR proposal_kind = 'bundle' OR state_version_used IS NOT NULL);

-- New status: 'superseded' = the reviewer asked for a revision and a new proposal replaced it.
ALTER TABLE proposals DROP CONSTRAINT proposals_status_check;
ALTER TABLE proposals ADD CONSTRAINT proposals_status_check
    CHECK (status IN ('pending_review', 'rejected_by_validator', 'approved',
                      'rejected_by_reviewer', 'stale', 'superseded'));

-- One row per resource the AI proposed. resource_id deliberately has NO foreign key.
CREATE TABLE proposal_items (
    item_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proposal_id   TEXT NOT NULL REFERENCES proposals (proposal_id),
    resource_type TEXT NOT NULL CHECK (resource_type IN ('bed', 'doctor', 'nurse', 'equipment')),
    resource_id   TEXT NOT NULL,
    version_used  INTEGER,   -- version the BACKEND read; NULL if the resource does not exist
    UNIQUE (proposal_id, resource_type, resource_id)
);

-- ============================================================ approvals (extended)

ALTER TABLE approvals ADD COLUMN reviewer_user_id BIGINT REFERENCES app_users (user_id);
ALTER TABLE approvals DROP CONSTRAINT approvals_decision_check;
ALTER TABLE approvals ADD CONSTRAINT approvals_decision_check
    CHECK (decision IN ('approved', 'rejected', 'revision_requested'));

-- ============================================================ allocations

-- One allocation = the complete resource bundle committed for ONE patient of ONE incident.
CREATE TABLE allocations (
    allocation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    hospital_id   TEXT NOT NULL,
    incident_id   TEXT NOT NULL,
    patient_id    TEXT NOT NULL,
    proposal_id   TEXT NOT NULL UNIQUE REFERENCES proposals (proposal_id),
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'released', 'cancelled')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at      TIMESTAMPTZ,
    end_reason    TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (incident_id, hospital_id) REFERENCES incidents (incident_id, hospital_id),
    -- The patient must actually be linked to that incident.
    FOREIGN KEY (incident_id, patient_id) REFERENCES incident_patients (incident_id, patient_id),
    UNIQUE (allocation_id, hospital_id),
    CONSTRAINT active_means_not_ended CHECK ((status = 'active') = (ended_at IS NULL))
);

CREATE UNIQUE INDEX one_active_allocation_per_patient
    ON allocations (patient_id) WHERE status = 'active';

CREATE TABLE allocation_items (
    item_id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    allocation_id     BIGINT NOT NULL,
    hospital_id       TEXT NOT NULL,
    resource_type     TEXT NOT NULL CHECK (resource_type IN ('bed', 'doctor', 'nurse', 'equipment')),
    bed_id            TEXT,
    doctor_id         TEXT,
    nurse_id          TEXT,
    equipment_unit_id TEXT,
    status            TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'released')),
    FOREIGN KEY (allocation_id, hospital_id)     REFERENCES allocations (allocation_id, hospital_id),
    FOREIGN KEY (bed_id, hospital_id)            REFERENCES beds (bed_id, hospital_id),
    FOREIGN KEY (doctor_id, hospital_id)         REFERENCES doctors (doctor_id, hospital_id),
    FOREIGN KEY (nurse_id, hospital_id)          REFERENCES nurses (nurse_id, hospital_id),
    FOREIGN KEY (equipment_unit_id, hospital_id) REFERENCES equipment_units (unit_id, hospital_id),
    -- Exactly one resource column is filled, and it matches resource_type.
    CONSTRAINT exactly_one_resource CHECK (
        (resource_type = 'bed'       AND bed_id IS NOT NULL AND doctor_id IS NULL AND nurse_id IS NULL AND equipment_unit_id IS NULL) OR
        (resource_type = 'doctor'    AND doctor_id IS NOT NULL AND bed_id IS NULL AND nurse_id IS NULL AND equipment_unit_id IS NULL) OR
        (resource_type = 'nurse'     AND nurse_id IS NOT NULL AND bed_id IS NULL AND doctor_id IS NULL AND equipment_unit_id IS NULL) OR
        (resource_type = 'equipment' AND equipment_unit_id IS NOT NULL AND bed_id IS NULL AND doctor_id IS NULL AND nurse_id IS NULL)
    )
);

-- Database backstops for exclusive resources (doctors and nurses may serve several
-- patients, limited by workload policy instead).
CREATE UNIQUE INDEX one_active_item_per_bed
    ON allocation_items (bed_id) WHERE status = 'active' AND bed_id IS NOT NULL;
CREATE UNIQUE INDEX one_active_item_per_equipment_unit
    ON allocation_items (equipment_unit_id) WHERE status = 'active' AND equipment_unit_id IS NOT NULL;
CREATE UNIQUE INDEX one_active_bed_per_allocation
    ON allocation_items (allocation_id) WHERE status = 'active' AND resource_type = 'bed';

-- ============================================================ audit log (extended)

ALTER TABLE audit_logs ADD COLUMN actor       TEXT NOT NULL DEFAULT 'system';
ALTER TABLE audit_logs ADD COLUMN entity_type TEXT;
ALTER TABLE audit_logs ADD COLUMN entity_id   TEXT;

-- Audit integrity: rows can be added but never changed or deleted.
CREATE FUNCTION audit_logs_are_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs is append-only (% is not allowed)', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_logs_no_update_or_delete
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION audit_logs_are_append_only();

-- ============================================================ indexes

CREATE INDEX idx_wards_hospital              ON wards (hospital_id);
CREATE INDEX idx_beds_lookup                 ON beds (hospital_id, ward_id, status);
CREATE INDEX idx_doctors_lookup              ON doctors (hospital_id, available);
CREATE INDEX idx_nurses_hospital             ON nurses (hospital_id, available);
CREATE INDEX idx_equipment_lookup            ON equipment_units (hospital_id, type_id, status);
CREATE INDEX idx_incidents_hospital_status   ON incidents (hospital_id, status);
CREATE INDEX idx_incident_patients_patient   ON incident_patients (patient_id);
CREATE INDEX idx_proposals_incident          ON proposals (incident_id);
CREATE INDEX idx_proposal_items_proposal     ON proposal_items (proposal_id);
CREATE INDEX idx_allocations_status          ON allocations (status);
CREATE INDEX idx_allocations_incident        ON allocations (incident_id);
CREATE INDEX idx_allocation_items_allocation ON allocation_items (allocation_id);
CREATE INDEX idx_audit_logs_entity           ON audit_logs (entity_type, entity_id);