-- Migration 001: the original nurse-only schema, unchanged.
-- Kept as the baseline so databases created by the earlier version of this project
-- upgrade cleanly. Every statement uses IF NOT EXISTS, so applying it to a database
-- that already has these tables does nothing.
-- RULE: never edit a migration after it has been applied anywhere. Add a new one instead.

CREATE TABLE IF NOT EXISTS nurses (
    nurse_id      TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    available     BOOLEAN NOT NULL,
    department    TEXT NOT NULL,
    state_version INTEGER NOT NULL DEFAULT 1 CHECK (state_version >= 1)
);

CREATE TABLE IF NOT EXISTS proposals (
    proposal_id          TEXT PRIMARY KEY,
    incident_description TEXT NOT NULL,
    proposed_nurse_id    TEXT NOT NULL,
    validation_valid     BOOLEAN NOT NULL,
    validation_reason    TEXT NOT NULL,
    state_version_used   INTEGER,
    status               TEXT NOT NULL CHECK (status IN (
                             'pending_review',
                             'rejected_by_validator',
                             'approved',
                             'rejected_by_reviewer',
                             'stale')),
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT valid_proposals_have_version
        CHECK (NOT validation_valid OR state_version_used IS NOT NULL),
    CONSTRAINT status_matches_validation
        CHECK ((status = 'rejected_by_validator') = (NOT validation_valid))
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proposal_id TEXT NOT NULL UNIQUE REFERENCES proposals (proposal_id),
    reviewer    TEXT NOT NULL CHECK (length(trim(reviewer)) > 0),
    decision    TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
    reason      TEXT NOT NULL DEFAULT '',
    decided_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS audit_logs (
    event_id    BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    proposal_id TEXT REFERENCES proposals (proposal_id),
    action      TEXT NOT NULL,
    details     JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_proposals_status      ON proposals (status);
CREATE INDEX IF NOT EXISTS idx_proposals_nurse       ON proposals (proposed_nurse_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_proposal   ON audit_logs (proposal_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs (created_at);
