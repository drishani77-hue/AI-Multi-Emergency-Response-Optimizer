-- ResQTech schema derived from §17 of 30PointsPlanning.md.
-- Apply PRAGMA foreign_keys = ON and PRAGMA busy_timeout = 5000 on EVERY connection.
-- WAL mode is enabled by connection initialization (PRAGMA journal_mode = WAL).
-- All persisted timestamps use UTC whole seconds exactly: YYYY-MM-DDTHH:MM:SSZ.
-- Never store fractional seconds or alternate ISO-8601 forms; lexical comparisons are then chronological.

CREATE TABLE IF NOT EXISTS Organizations (
    organization_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    organization_type TEXT NOT NULL CHECK (organization_type IN ('HOSPITAL_MEDICAL', 'FIRE_SERVICE', 'POLICE_SECURITY', 'RESCUE_DISASTER_RESPONSE')),
    ownership TEXT NOT NULL CHECK (ownership IN ('GOVERNMENT', 'PRIVATE')),
    phone TEXT,
    email TEXT,
    password_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'INACTIVE'))
);

-- Organization login email is unique after trimming and case normalization.
-- The registration API requires a non-empty email; NULL/blank legacy rows are excluded.
CREATE UNIQUE INDEX IF NOT EXISTS uq_organizations_email_normalized
    ON Organizations(lower(trim(email)))
    WHERE email IS NOT NULL AND trim(email) <> '';


-- Server-side sessions for both organization and environment-backed Admin principals.
-- Only SHA-256 digests are stored; raw cookie/CSRF tokens are never persisted.
CREATE TABLE IF NOT EXISTS Sessions (
    session_token_hash TEXT PRIMARY KEY
        CHECK (length(session_token_hash) = 64 AND session_token_hash NOT GLOB '*[^0-9a-f]*'),
    csrf_token_hash TEXT NOT NULL
        CHECK (length(csrf_token_hash) = 64 AND csrf_token_hash NOT GLOB '*[^0-9a-f]*'),
    principal_type TEXT NOT NULL CHECK (principal_type IN ('ORGANIZATION', 'ADMIN')),
    principal_id TEXT NOT NULL CHECK (length(trim(principal_id)) > 0),
    organization_id TEXT REFERENCES Organizations(organization_id) ON DELETE CASCADE,
    created_at TEXT NOT NULL CHECK ((created_at GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z' AND substr(created_at,1,4) BETWEEN '0001' AND '9999' AND substr(created_at,6,2) BETWEEN '01' AND '12' AND substr(created_at,9,2) BETWEEN '01' AND '31' AND substr(created_at,12,2) BETWEEN '00' AND '23')),
    expires_at TEXT NOT NULL CHECK ((expires_at GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z' AND substr(expires_at,1,4) BETWEEN '0001' AND '9999' AND substr(expires_at,6,2) BETWEEN '01' AND '12' AND substr(expires_at,9,2) BETWEEN '01' AND '31' AND substr(expires_at,12,2) BETWEEN '00' AND '23')),
    revoked_at TEXT CHECK (revoked_at IS NULL OR (revoked_at GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z' AND substr(revoked_at,1,4) BETWEEN '0001' AND '9999' AND substr(revoked_at,6,2) BETWEEN '01' AND '12' AND substr(revoked_at,9,2) BETWEEN '01' AND '31' AND substr(revoked_at,12,2) BETWEEN '00' AND '23')),
    CHECK (expires_at > created_at),
    CHECK (revoked_at IS NULL OR revoked_at >= created_at),
    CHECK (
        (principal_type = 'ORGANIZATION' AND organization_id IS NOT NULL AND principal_id = organization_id)
        OR (principal_type = 'ADMIN' AND organization_id IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON Sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_sessions_organization ON Sessions(organization_id);
CREATE INDEX IF NOT EXISTS idx_sessions_principal_active
    ON Sessions(principal_type, principal_id, expires_at)
    WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS Locations (
    location_id TEXT PRIMARY KEY,
    district TEXT NOT NULL,
    locality TEXT NOT NULL,
    specific_location TEXT NOT NULL,
    latitude REAL,
    longitude REAL,
    road_node_id TEXT,
    CHECK (latitude IS NULL OR latitude BETWEEN -90 AND 90),
    CHECK (longitude IS NULL OR longitude BETWEEN -180 AND 180)
);

CREATE TABLE IF NOT EXISTS Resources (
    resource_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES Organizations(organization_id),
    resource_type TEXT NOT NULL CHECK (resource_type IN ('AMBULANCE', 'FIRE_VEHICLE', 'POLICE_UNIT', 'RESCUE_VEHICLE')),
    base_location_id TEXT REFERENCES Locations(location_id),
    last_reported_location_id TEXT REFERENCES Locations(location_id),
    status TEXT NOT NULL CHECK (status IN ('AVAILABLE', 'REQUESTED', 'DISPATCHED', 'UNAVAILABLE', 'INACTIVE')),
    last_updated TEXT NOT NULL CHECK ((last_updated GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z' AND substr(last_updated,1,4) BETWEEN '0001' AND '9999' AND substr(last_updated,6,2) BETWEEN '01' AND '12' AND substr(last_updated,9,2) BETWEEN '01' AND '31' AND substr(last_updated,12,2) BETWEEN '00' AND '23'))
);

CREATE TABLE IF NOT EXISTS Emergencies (
    emergency_id TEXT PRIMARY KEY,
    emergency_type TEXT NOT NULL CHECK (emergency_type IN ('MEDICAL_EMERGENCY', 'FIRE', 'ROAD_TRAFFIC_ACCIDENT', 'THREAT_TO_LIFE_VIOLENCE', 'TRAPPED_PERSON_RESCUE')),
    severity TEXT NOT NULL CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    location_id TEXT REFERENCES Locations(location_id),
    additional_details TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL,
    reporter_name TEXT NOT NULL,
    reporter_phone TEXT NOT NULL,
    reporter_type TEXT NOT NULL CHECK (reporter_type IN ('CITIZEN', 'BYSTANDER', 'AUTHORIZED_EMERGENCY_OPERATOR')),
    reported_at TEXT NOT NULL CHECK ((reported_at GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z' AND substr(reported_at,1,4) BETWEEN '0001' AND '9999' AND substr(reported_at,6,2) BETWEEN '01' AND '12' AND substr(reported_at,9,2) BETWEEN '01' AND '31' AND substr(reported_at,12,2) BETWEEN '00' AND '23')),
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'PARTIALLY_ALLOCATED', 'FULLY_ALLOCATED', 'COMPLETED', 'UNFULFILLED')),
    data_source TEXT NOT NULL DEFAULT 'OPERATIONAL' CHECK (data_source IN ('OPERATIONAL', 'SIMULATED', 'PROJECT_GENERATED', 'PUBLIC')),
    idempotency_key TEXT NOT NULL UNIQUE,
    location_text TEXT NOT NULL DEFAULT '',
    location_resolved INTEGER NOT NULL DEFAULT 1 CHECK (location_resolved IN (0, 1)),
    assessment_answers_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(assessment_answers_json)),
    assessment_uncertain INTEGER NOT NULL DEFAULT 0 CHECK (assessment_uncertain IN (0, 1)),
    assessment_reasons TEXT NOT NULL DEFAULT '',
    severity_rule_version TEXT NOT NULL DEFAULT 'triage-v1',
    CHECK ((location_resolved = 1 AND location_id IS NOT NULL) OR location_resolved = 0)
);

CREATE TABLE IF NOT EXISTS Severity_Audit_History (
    severity_audit_id TEXT PRIMARY KEY,
    emergency_id TEXT NOT NULL REFERENCES Emergencies(emergency_id),
    old_severity TEXT NOT NULL CHECK (old_severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    new_severity TEXT NOT NULL CHECK (new_severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')) CHECK (new_severity <> old_severity),
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    actor_id TEXT NOT NULL CHECK (length(trim(actor_id)) > 0),
    changed_at TEXT NOT NULL CHECK ((changed_at GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z' AND substr(changed_at,1,4) BETWEEN '0001' AND '9999' AND substr(changed_at,6,2) BETWEEN '01' AND '12' AND substr(changed_at,9,2) BETWEEN '01' AND '31' AND substr(changed_at,12,2) BETWEEN '00' AND '23')),
    change_kind TEXT NOT NULL CHECK (change_kind IN ('OPERATIONAL_OVERRIDE', 'HISTORICAL_CORRECTION'))
);

CREATE TABLE IF NOT EXISTS Requirement_Groups (
    requirement_group_id TEXT PRIMARY KEY,
    emergency_id TEXT NOT NULL REFERENCES Emergencies(emergency_id),
    resource_type TEXT NOT NULL CHECK (resource_type IN ('AMBULANCE', 'FIRE_VEHICLE', 'POLICE_UNIT', 'RESCUE_VEHICLE')),
    quantity_required INTEGER NOT NULL CHECK (quantity_required > 0),
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'PARTIALLY_ALLOCATED', 'FULLY_ALLOCATED', 'COMPLETED', 'UNFULFILLED')),
    UNIQUE (emergency_id, resource_type)
);

CREATE TABLE IF NOT EXISTS Requirement_Units (
    requirement_unit_id TEXT PRIMARY KEY,
    requirement_group_id TEXT NOT NULL REFERENCES Requirement_Groups(requirement_group_id),
    unit_number INTEGER NOT NULL CHECK (unit_number > 0),
    resource_type TEXT NOT NULL CHECK (resource_type IN ('AMBULANCE', 'FIRE_VEHICLE', 'POLICE_UNIT', 'RESCUE_VEHICLE')),
    status TEXT NOT NULL CHECK (status IN ('PENDING', 'REQUESTED', 'DISPATCHED', 'FULFILLED', 'UNFULFILLED', 'CANCELLED')),
    pending_since TEXT CHECK (pending_since IS NULL OR (pending_since GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z' AND substr(pending_since,1,4) BETWEEN '0001' AND '9999' AND substr(pending_since,6,2) BETWEEN '01' AND '12' AND substr(pending_since,9,2) BETWEEN '01' AND '31' AND substr(pending_since,12,2) BETWEEN '00' AND '23')),
    expires_at TEXT CHECK (expires_at IS NULL OR (expires_at GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z' AND substr(expires_at,1,4) BETWEEN '0001' AND '9999' AND substr(expires_at,6,2) BETWEEN '01' AND '12' AND substr(expires_at,9,2) BETWEEN '01' AND '31' AND substr(expires_at,12,2) BETWEEN '00' AND '23')),
    episode_count INTEGER NOT NULL DEFAULT 0 CHECK (episode_count >= 0),
    UNIQUE (requirement_group_id, unit_number),
    CHECK ((pending_since IS NULL AND expires_at IS NULL) OR (pending_since IS NOT NULL AND expires_at IS NOT NULL)),
    CHECK (status NOT IN ('DISPATCHED', 'FULFILLED', 'UNFULFILLED', 'CANCELLED') OR pending_since IS NULL),
    CHECK (expires_at IS NULL OR expires_at > pending_since)
);

CREATE TABLE IF NOT EXISTS Allocations (
    allocation_id TEXT PRIMARY KEY,
    emergency_id TEXT NOT NULL REFERENCES Emergencies(emergency_id),
    requirement_unit_id TEXT NOT NULL REFERENCES Requirement_Units(requirement_unit_id),
    resource_id TEXT NOT NULL REFERENCES Resources(resource_id),
    requested_at TEXT NOT NULL CHECK ((requested_at GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z' AND substr(requested_at,1,4) BETWEEN '0001' AND '9999' AND substr(requested_at,6,2) BETWEEN '01' AND '12' AND substr(requested_at,9,2) BETWEEN '01' AND '31' AND substr(requested_at,12,2) BETWEEN '00' AND '23')),
    deadline_at TEXT NOT NULL CHECK ((deadline_at GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z' AND substr(deadline_at,1,4) BETWEEN '0001' AND '9999' AND substr(deadline_at,6,2) BETWEEN '01' AND '12' AND substr(deadline_at,9,2) BETWEEN '01' AND '31' AND substr(deadline_at,12,2) BETWEEN '00' AND '23')),
    response_at TEXT CHECK (response_at IS NULL OR (response_at GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z' AND substr(response_at,1,4) BETWEEN '0001' AND '9999' AND substr(response_at,6,2) BETWEEN '01' AND '12' AND substr(response_at,9,2) BETWEEN '01' AND '31' AND substr(response_at,12,2) BETWEEN '00' AND '23')),
    response_status TEXT NOT NULL CHECK (response_status IN ('PENDING', 'ACCEPTED', 'REJECTED', 'TIMEOUT', 'CANCELLED')),
    rejection_reason TEXT,
    distance_km REAL NOT NULL CHECK (distance_km >= 0),
    status TEXT NOT NULL CHECK (status IN ('REQUESTED', 'DISPATCHED', 'COMPLETED', 'FAILED', 'CLOSED')),
    dispatched_at TEXT CHECK (dispatched_at IS NULL OR (dispatched_at GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z' AND substr(dispatched_at,1,4) BETWEEN '0001' AND '9999' AND substr(dispatched_at,6,2) BETWEEN '01' AND '12' AND substr(dispatched_at,9,2) BETWEEN '01' AND '31' AND substr(dispatched_at,12,2) BETWEEN '00' AND '23')),
    completed_at TEXT CHECK (completed_at IS NULL OR (completed_at GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z' AND substr(completed_at,1,4) BETWEEN '0001' AND '9999' AND substr(completed_at,6,2) BETWEEN '01' AND '12' AND substr(completed_at,9,2) BETWEEN '01' AND '31' AND substr(completed_at,12,2) BETWEEN '00' AND '23')),
    returned_at TEXT CHECK (returned_at IS NULL OR (returned_at GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z' AND substr(returned_at,1,4) BETWEEN '0001' AND '9999' AND substr(returned_at,6,2) BETWEEN '01' AND '12' AND substr(returned_at,9,2) BETWEEN '01' AND '31' AND substr(returned_at,12,2) BETWEEN '00' AND '23')),
    CHECK (
        (status = 'REQUESTED' AND response_status = 'PENDING') OR
        (status = 'DISPATCHED' AND response_status = 'ACCEPTED') OR
        (status = 'COMPLETED' AND response_status = 'ACCEPTED') OR
        (status = 'FAILED' AND response_status = 'ACCEPTED') OR
        (status = 'CLOSED' AND response_status IN ('REJECTED', 'TIMEOUT', 'CANCELLED'))
    ),
    CHECK (status NOT IN ('DISPATCHED', 'COMPLETED', 'FAILED') OR dispatched_at IS NOT NULL),
    CHECK (status <> 'COMPLETED' OR (completed_at IS NOT NULL AND returned_at IS NOT NULL)),
    CHECK (status = 'REQUESTED' OR response_at IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS Response_History (
    history_id TEXT PRIMARY KEY,
    allocation_id TEXT NOT NULL UNIQUE REFERENCES Allocations(allocation_id),
    final_status TEXT NOT NULL CHECK (final_status IN ('COMPLETED', 'FAILED'))
);

CREATE TABLE IF NOT EXISTS Allocation_Decision_Events (
    event_id TEXT PRIMARY KEY,
    emergency_id TEXT NOT NULL REFERENCES Emergencies(emergency_id),
    requirement_unit_id TEXT NOT NULL REFERENCES Requirement_Units(requirement_unit_id),
    resource_id TEXT REFERENCES Resources(resource_id),
    event_type TEXT NOT NULL CHECK (event_type IN ('ALLOCATION_REQUESTED', 'ACCEPTED', 'REJECTED', 'TIMEOUT', 'CANCELLED', 'NO_ROUTE', 'NO_SUITABLE_RESOURCE', 'FAILED', 'COMPLETED', 'PENDING_STARTED', 'UNFULFILLED')),
    event_time TEXT NOT NULL CHECK ((event_time GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z' AND substr(event_time,1,4) BETWEEN '0001' AND '9999' AND substr(event_time,6,2) BETWEEN '01' AND '12' AND substr(event_time,9,2) BETWEEN '01' AND '31' AND substr(event_time,12,2) BETWEEN '00' AND '23')),
    distance_km REAL CHECK (distance_km IS NULL OR distance_km >= 0),
    reason TEXT
);

CREATE TABLE IF NOT EXISTS ML_Feature_Snapshots (
    snapshot_id TEXT PRIMARY KEY,
    requirement_unit_id TEXT NOT NULL UNIQUE REFERENCES Requirement_Units(requirement_unit_id),
    snapshot_at TEXT NOT NULL CHECK ((snapshot_at GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]Z' AND substr(snapshot_at,1,4) BETWEEN '0001' AND '9999' AND substr(snapshot_at,6,2) BETWEEN '01' AND '12' AND substr(snapshot_at,9,2) BETWEEN '01' AND '31' AND substr(snapshot_at,12,2) BETWEEN '00' AND '23')),
    available_resource_count INTEGER NOT NULL CHECK (available_resource_count >= 0),
    active_emergency_count INTEGER NOT NULL CHECK (active_emergency_count >= 0),
    higher_priority_pending_count INTEGER NOT NULL CHECK (higher_priority_pending_count >= 0),
    nearest_eligible_distance_km REAL CHECK (nearest_eligible_distance_km IS NULL OR nearest_eligible_distance_km >= 0),
    time_of_day INTEGER,
    day_of_week INTEGER,
    emergency_type TEXT,
    severity TEXT,
    resource_type TEXT,
    locality TEXT,
    data_source TEXT NOT NULL CHECK (data_source IN ('OPERATIONAL', 'SIMULATED', 'PROJECT_GENERATED', 'PUBLIC'))
);

-- Any recorded attempt permanently excludes this resource for this requirement unit.
-- Reservation races that fail before an Allocation row is created are unaffected.
CREATE UNIQUE INDEX IF NOT EXISTS uq_allocations_unit_resource_attempt
    ON Allocations(requirement_unit_id, resource_id);
CREATE INDEX IF NOT EXISTS idx_allocations_resource_status
    ON Allocations(resource_id, status);
CREATE INDEX IF NOT EXISTS idx_requirement_units_status_type
    ON Requirement_Units(status, resource_type);
CREATE INDEX IF NOT EXISTS idx_requirement_units_status_expires
    ON Requirement_Units(status, expires_at);
CREATE INDEX IF NOT EXISTS idx_allocations_status_deadline
    ON Allocations(status, deadline_at);
CREATE INDEX IF NOT EXISTS idx_emergencies_reported_status
    ON Emergencies(reported_at, status);
CREATE INDEX IF NOT EXISTS idx_severity_audit_emergency_time
    ON Severity_Audit_History(emergency_id, changed_at);
CREATE INDEX IF NOT EXISTS idx_decision_events_unit_resource_type
    ON Allocation_Decision_Events(requirement_unit_id, resource_id, event_type);
CREATE INDEX IF NOT EXISTS idx_snapshots_unit_time
    ON ML_Feature_Snapshots(requirement_unit_id, snapshot_at);

-- Canonical invariant: REQUESTED and DISPATCHED are the only statuses that hold a resource.
CREATE UNIQUE INDEX IF NOT EXISTS uq_allocations_one_active_per_resource
    ON Allocations(resource_id)
    WHERE status IN ('REQUESTED', 'DISPATCHED');


-- One active allocation per requirement unit.
CREATE UNIQUE INDEX IF NOT EXISTS uq_allocations_one_active_per_unit
    ON Allocations(requirement_unit_id)
    WHERE status IN ('REQUESTED', 'DISPATCHED');

-- Resource type is immutable after creation.
CREATE TRIGGER IF NOT EXISTS trg_resource_type_immutable
BEFORE UPDATE OF resource_type ON Resources
WHEN OLD.resource_type <> NEW.resource_type
BEGIN
    SELECT RAISE(ABORT, 'resource_type is immutable');
END;

-- A resource's routing base cannot change while an allocation request is active or dispatched.
CREATE TRIGGER IF NOT EXISTS trg_base_location_locked
BEFORE UPDATE OF base_location_id ON Resources
WHEN OLD.status IN ('REQUESTED', 'DISPATCHED')
 AND OLD.base_location_id IS NOT NEW.base_location_id
BEGIN
    SELECT RAISE(ABORT, 'base_location_id locked while REQUESTED/DISPATCHED');
END;


-- An Allocation may only pair a resource with a Requirement Unit/Group of the same type.
CREATE TRIGGER IF NOT EXISTS trg_allocation_resource_type_matches_unit_insert
BEFORE INSERT ON Allocations
WHEN EXISTS (
    SELECT 1
    FROM Resources r
    JOIN Requirement_Units ru ON ru.requirement_unit_id = NEW.requirement_unit_id
    JOIN Requirement_Groups rg ON rg.requirement_group_id = ru.requirement_group_id
    WHERE r.resource_id = NEW.resource_id
      AND (r.resource_type <> ru.resource_type OR ru.resource_type <> rg.resource_type)
)
BEGIN
    SELECT RAISE(ABORT, 'resource type does not match requirement unit/group');
END;

CREATE TRIGGER IF NOT EXISTS trg_allocation_resource_type_matches_unit_update
BEFORE UPDATE OF resource_id, requirement_unit_id ON Allocations
WHEN EXISTS (
    SELECT 1
    FROM Resources r
    JOIN Requirement_Units ru ON ru.requirement_unit_id = NEW.requirement_unit_id
    JOIN Requirement_Groups rg ON rg.requirement_group_id = ru.requirement_group_id
    WHERE r.resource_id = NEW.resource_id
      AND (r.resource_type <> ru.resource_type OR ru.resource_type <> rg.resource_type)
)
BEGIN
    SELECT RAISE(ABORT, 'resource type does not match requirement unit/group');
END;

-- Allocation emergency_id must match the Emergency reached through its Requirement Unit and Group.
CREATE TRIGGER IF NOT EXISTS trg_allocation_emergency_matches_unit_insert
BEFORE INSERT ON Allocations
WHEN NEW.emergency_id <> (
    SELECT rg.emergency_id
    FROM Requirement_Units ru
    JOIN Requirement_Groups rg ON rg.requirement_group_id = ru.requirement_group_id
    WHERE ru.requirement_unit_id = NEW.requirement_unit_id
)
BEGIN
    SELECT RAISE(ABORT, 'allocation emergency_id does not match requirement unit');
END;

CREATE TRIGGER IF NOT EXISTS trg_allocation_emergency_matches_unit_update
BEFORE UPDATE OF emergency_id, requirement_unit_id ON Allocations
WHEN NEW.emergency_id <> (
    SELECT rg.emergency_id
    FROM Requirement_Units ru
    JOIN Requirement_Groups rg ON rg.requirement_group_id = ru.requirement_group_id
    WHERE ru.requirement_unit_id = NEW.requirement_unit_id
)
BEGIN
    SELECT RAISE(ABORT, 'allocation emergency_id does not match requirement unit');
END;


-- Keep Requirement Unit and parent Requirement Group resource types aligned.
CREATE TRIGGER IF NOT EXISTS trg_requirement_unit_type_matches_group_insert
BEFORE INSERT ON Requirement_Units
WHEN NEW.resource_type <> (
    SELECT resource_type FROM Requirement_Groups
    WHERE requirement_group_id = NEW.requirement_group_id
)
BEGIN
    SELECT RAISE(ABORT, 'requirement unit resource type does not match group');
END;

CREATE TRIGGER IF NOT EXISTS trg_requirement_unit_type_matches_group_update
BEFORE UPDATE OF resource_type, requirement_group_id ON Requirement_Units
WHEN NEW.resource_type <> (
    SELECT resource_type FROM Requirement_Groups
    WHERE requirement_group_id = NEW.requirement_group_id
)
BEGIN
    SELECT RAISE(ABORT, 'requirement unit resource type does not match group');
END;

-- Parent requirement groups cannot be re-parented or re-typed after units exist.
CREATE TRIGGER IF NOT EXISTS trg_requirement_group_identity_locked_with_units
BEFORE UPDATE OF emergency_id, resource_type ON Requirement_Groups
WHEN (OLD.emergency_id <> NEW.emergency_id OR OLD.resource_type <> NEW.resource_type)
 AND EXISTS (SELECT 1 FROM Requirement_Units ru
             WHERE ru.requirement_group_id = OLD.requirement_group_id)
BEGIN
    SELECT RAISE(ABORT, 'requirement group emergency/resource type locked while units exist');
END;

-- A Requirement Unit's parent/type cannot change after allocation history exists.
CREATE TRIGGER IF NOT EXISTS trg_requirement_unit_identity_locked_with_allocations
BEFORE UPDATE OF requirement_group_id, resource_type ON Requirement_Units
WHEN (OLD.requirement_group_id <> NEW.requirement_group_id
      OR OLD.resource_type <> NEW.resource_type)
 AND EXISTS (SELECT 1 FROM Allocations a
             WHERE a.requirement_unit_id = OLD.requirement_unit_id)
BEGIN
    SELECT RAISE(ABORT, 'requirement unit group/resource type locked after allocation history');
END;

-- Materialized Requirement Group quantity/status may only be updated when they
-- match the already-reconciled non-CANCELLED child units. The reconciliation
-- service updates units first, then writes these parent summary fields in the
-- same transaction. This prevents direct parent edits from contradicting units.
CREATE TRIGGER IF NOT EXISTS trg_requirement_group_summary_matches_units
BEFORE UPDATE OF quantity_required, status ON Requirement_Groups
BEGIN
    SELECT CASE
      WHEN (SELECT COUNT(*) FROM Requirement_Units ru
            WHERE ru.requirement_group_id = NEW.requirement_group_id
              AND ru.status <> 'CANCELLED') <> NEW.quantity_required
      THEN RAISE(ABORT, 'requirement group quantity must equal non-CANCELLED unit count')
    END;
    SELECT CASE
      WHEN (SELECT COUNT(*) FROM Requirement_Units ru
            WHERE ru.requirement_group_id = NEW.requirement_group_id
              AND ru.status <> 'CANCELLED') = 0
      THEN RAISE(ABORT, 'requirement group must retain at least one active unit')
      WHEN NEW.status <> (
        SELECT CASE
          WHEN EXISTS (SELECT 1 FROM Requirement_Units ru
                       WHERE ru.requirement_group_id = NEW.requirement_group_id
                         AND ru.status = 'UNFULFILLED')
            THEN 'UNFULFILLED'
          WHEN NOT EXISTS (SELECT 1 FROM Requirement_Units ru
                           WHERE ru.requirement_group_id = NEW.requirement_group_id
                             AND ru.status NOT IN ('CANCELLED', 'FULFILLED'))
            THEN 'COMPLETED'
          WHEN NOT EXISTS (SELECT 1 FROM Requirement_Units ru
                           WHERE ru.requirement_group_id = NEW.requirement_group_id
                             AND ru.status NOT IN ('CANCELLED', 'DISPATCHED', 'FULFILLED'))
               AND EXISTS (SELECT 1 FROM Requirement_Units ru
                           WHERE ru.requirement_group_id = NEW.requirement_group_id
                             AND ru.status = 'DISPATCHED')
            THEN 'FULLY_ALLOCATED'
          WHEN EXISTS (SELECT 1 FROM Requirement_Units ru
                       WHERE ru.requirement_group_id = NEW.requirement_group_id
                         AND ru.status IN ('DISPATCHED', 'FULFILLED'))
            THEN 'PARTIALLY_ALLOCATED'
          ELSE 'PENDING'
        END
      )
      THEN RAISE(ABORT, 'requirement group status does not match child unit states')
    END;
END;

-- Severity audit history is append-only. Corrections require a new audit row.
CREATE TRIGGER IF NOT EXISTS trg_severity_audit_no_update
BEFORE UPDATE ON Severity_Audit_History
BEGIN
    SELECT RAISE(ABORT, 'severity audit history is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_severity_audit_no_delete
BEFORE DELETE ON Severity_Audit_History
BEGIN
    SELECT RAISE(ABORT, 'severity audit history is append-only');
END;