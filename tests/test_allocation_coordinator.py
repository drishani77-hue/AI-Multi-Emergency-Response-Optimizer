import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from backend.allocation_coordinator import AllocationCoordinator
from backend.db import SCHEMA_PATH


REPORTED_AT = "2026-11-12T12:00:00Z"
NOW = "2026-11-12T12:01:00Z"


class FakeRoadEngine:
    """Deterministic road-ranking test double."""

    def __init__(self, distances=None):
        self.distances = distances or {}

    def rank_resources(self, emergency_osm_id, candidates):
        ranked = []
        for candidate in candidates:
            resource_id = candidate["resource_id"]
            if resource_id not in self.distances:
                continue
            distance_km = self.distances[resource_id]
            ranked.append(
                {
                    "resource_id": resource_id,
                    "base_osm_id": candidate["base_osm_id"],
                    "distance_metres": distance_km * 1000,
                    "distance_km": distance_km,
                }
            )
        return sorted(
            ranked,
            key=lambda item: (item["distance_km"], item["resource_id"]),
        )


@pytest.fixture
def allocation_environment(tmp_path):
    db_path = tmp_path / "allocation_coordinator.db"
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    connection.execute(
        """
        INSERT INTO Organizations (
            organization_id, name, organization_type, ownership,
            phone, email, password_hash, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ORG001",
            "Test MEDICAL_EMERGENCY Organization",
            "HOSPITAL_MEDICAL",
            "GOVERNMENT",
            "9876543210",
            "test-org@example.com",
            "test-password-hash",
            "ACTIVE",
        ),
    )

    connection.execute(
        """
        INSERT INTO Locations (
            location_id, district, locality, specific_location,
            latitude, longitude, road_node_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "LOC_EMERGENCY",
            "Dehradun",
            "Clement Town",
            "Graphic Era University Gate 1",
            30.269,
            77.995,
            "1001",
        ),
    )

    connection.execute(
        """
        INSERT INTO Locations (
            location_id, district, locality, specific_location,
            latitude, longitude, road_node_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "LOC_RESOURCE_1",
            "Dehradun",
            "Clement Town",
            "Resource Base 1",
            30.270,
            77.996,
            "1002",
        ),
    )
    connection.execute(
        """
        INSERT INTO Locations (
            location_id, district, locality, specific_location,
            latitude, longitude, road_node_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "LOC_RESOURCE_2",
            "Dehradun",
            "Clement Town",
            "Resource Base 2",
            30.271,
            77.997,
            "1003",
        ),
    )

    connection.execute(
        """
        INSERT INTO Emergencies (
            emergency_id, emergency_type, severity, location_id,
            description, reporter_name, reporter_phone, reporter_type,
            reported_at, status, idempotency_key, location_text,
            location_resolved
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "EMG001",
            "MEDICAL_EMERGENCY",
            "HIGH",
            "LOC_EMERGENCY",
            "Coordinator test emergency",
            "Test Reporter",
            "9876543210",
            "CITIZEN",
            REPORTED_AT,
            "PENDING",
            "coordinator-test-emergency-1",
            "Graphic Era University Gate 1, Dehradun",
            1,
        ),
    )

    connection.execute(
        """
        INSERT INTO Requirement_Groups (
            requirement_group_id, emergency_id, resource_type,
            quantity_required, status
        ) VALUES (?, ?, ?, ?, ?)
        """,
        ("GRP001", "EMG001", "AMBULANCE", 1, "PENDING"),
    )

    connection.execute(
        """
        INSERT INTO Requirement_Units (
            requirement_unit_id, requirement_group_id, unit_number,
            resource_type, status, pending_since, expires_at, episode_count
        ) VALUES (?, ?, ?, ?, ?, NULL, NULL, 0)
        """,
        ("UNIT001", "GRP001", 1, "AMBULANCE", "PENDING"),
    )

    for resource_id, location_id in (
        ("RES001", "LOC_RESOURCE_1"),
        ("RES002", "LOC_RESOURCE_2"),
    ):
        connection.execute(
            """
            INSERT INTO Resources (
                resource_id, organization_id, resource_type,
                base_location_id, last_reported_location_id,
                status, last_updated
            ) VALUES (?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                resource_id,
                "ORG001",
                "AMBULANCE",
                location_id,
                "AVAILABLE",
                REPORTED_AT,
            ),
        )

    connection.commit()
    connection.close()
    return db_path


@pytest.fixture
def coordinator(allocation_environment):
    instance = AllocationCoordinator(
        allocation_environment,
        FakeRoadEngine({"RES001": 4.0, "RES002": 2.0}),
    )
    yield instance
    instance.close()


def fetch_one(db_path, query, parameters=()):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        return connection.execute(query, parameters).fetchone()
    finally:
        connection.close()


def test_coordinator_reserves_nearest_eligible_resource(
    allocation_environment,
    coordinator,
):
    requests = coordinator.run_coordinator_pass()

    assert len(requests) == 1
    assert requests[0]["resource_id"] == "RES002"
    assert requests[0]["requirement_unit_id"] == "UNIT001"
    assert requests[0]["distance_km"] == pytest.approx(2.0)

    unit = fetch_one(
        allocation_environment,
        "SELECT status FROM Requirement_Units WHERE requirement_unit_id = ?",
        ("UNIT001",),
    )
    resource = fetch_one(
        allocation_environment,
        "SELECT status FROM Resources WHERE resource_id = ?",
        ("RES002",),
    )
    allocation = fetch_one(
        allocation_environment,
        """
        SELECT status, response_status, resource_id
        FROM Allocations WHERE allocation_id = ?
        """,
        (requests[0]["allocation_id"],),
    )
    event = fetch_one(
        allocation_environment,
        """
        SELECT event_type, resource_id
        FROM Allocation_Decision_Events
        WHERE requirement_unit_id = ?
        ORDER BY event_time DESC, event_id DESC LIMIT 1
        """,
        ("UNIT001",),
    )

    assert unit["status"] == "REQUESTED"
    assert resource["status"] == "REQUESTED"
    assert allocation["status"] == "REQUESTED"
    assert allocation["response_status"] == "PENDING"
    assert allocation["resource_id"] == "RES002"
    assert event["event_type"] == "ALLOCATION_REQUESTED"
    assert event["resource_id"] == "RES002"



def test_ml_feature_snapshot_is_accurate_and_preserved_on_retry(
    allocation_environment,
    coordinator,
):
    first_time = datetime(2026, 11, 12, 12, 1, tzinfo=timezone.utc)
    coordinator.run_coordinator_pass(now=first_time)

    snapshot = fetch_one(
        allocation_environment,
        """
        SELECT *
        FROM ML_Feature_Snapshots
        WHERE requirement_unit_id = ?
        """,
        ("UNIT001",),
    )

    assert snapshot is not None
    assert snapshot["snapshot_at"] == "2026-11-12T12:01:00Z"
    assert snapshot["available_resource_count"] == 2
    assert snapshot["active_emergency_count"] == 1
    assert snapshot["higher_priority_pending_count"] == 0
    assert snapshot["nearest_eligible_distance_km"] == pytest.approx(2.0)
    assert snapshot["time_of_day"] == 12
    assert snapshot["day_of_week"] == 3
    assert snapshot["emergency_type"] == "MEDICAL_EMERGENCY"
    assert snapshot["severity"] == "HIGH"
    assert snapshot["resource_type"] == "AMBULANCE"
    assert snapshot["locality"] == "Clement Town"
    assert snapshot["data_source"] == "OPERATIONAL"

    connection = sqlite3.connect(allocation_environment)
    connection.execute(
        "UPDATE Emergencies SET severity = ?, data_source = ? WHERE emergency_id = ?",
        ("CRITICAL", "SIMULATED", "EMG001"),
    )
    connection.execute(
        "UPDATE Requirement_Units SET status = 'PENDING' WHERE requirement_unit_id = ?",
        ("UNIT001",),
    )
    connection.commit()
    connection.close()

    second_time = datetime(2026, 11, 12, 12, 2, tzinfo=timezone.utc)
    connection = sqlite3.connect(allocation_environment)
    connection.row_factory = sqlite3.Row
    try:
        coordinator._capture_ml_feature_snapshot(
            connection,
            "UNIT001",
            "EMG001",
            "AMBULANCE",
            second_time,
            [],
        )
        connection.commit()
    finally:
        connection.close()

    preserved = fetch_one(
        allocation_environment,
        """
        SELECT *
        FROM ML_Feature_Snapshots
        WHERE requirement_unit_id = ?
        """,
        ("UNIT001",),
    )

    assert preserved["snapshot_at"] == "2026-11-12T12:01:00Z"
    assert preserved["severity"] == "HIGH"
    assert preserved["data_source"] == "OPERATIONAL"
    assert preserved["available_resource_count"] == 2


def test_no_routable_candidate_starts_one_pending_episode(
    allocation_environment,
):
    coordinator = AllocationCoordinator(
        allocation_environment,
        FakeRoadEngine({}),
        pending_episode_seconds=300,
    )
    try:
        requests = coordinator.run_coordinator_pass()
        assert requests == []

        unit = fetch_one(
            allocation_environment,
            """
            SELECT status, pending_since, expires_at, episode_count
            FROM Requirement_Units WHERE requirement_unit_id = ?
            """,
            ("UNIT001",),
        )
        assert unit["status"] == "PENDING"
        assert unit["pending_since"] is not None
        assert unit["expires_at"] is not None
        assert unit["episode_count"] == 1

        event = fetch_one(
            allocation_environment,
            """
            SELECT COUNT(*) AS count
            FROM Allocation_Decision_Events
            WHERE requirement_unit_id = ? AND event_type = 'PENDING_STARTED'
            """,
            ("UNIT001",),
        )
        assert event["count"] == 1
    finally:
        coordinator.close()


def test_previously_attempted_resource_is_permanently_excluded(
    allocation_environment,
):
    connection = sqlite3.connect(allocation_environment)
    connection.execute(
        """
        INSERT INTO Allocations (
            allocation_id, emergency_id, requirement_unit_id, resource_id,
            requested_at, deadline_at, response_at, response_status,
            rejection_reason, distance_km, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ALLOC_OLD",
            "EMG001",
            "UNIT001",
            "RES002",
            REPORTED_AT,
            "2026-11-12T12:00:30Z",
            "2026-11-12T12:00:10Z",
            "REJECTED",
            "Previously rejected",
            2.0,
            "CLOSED",
        ),
    )
    connection.commit()
    connection.close()

    coordinator = AllocationCoordinator(
        allocation_environment,
        FakeRoadEngine({"RES001": 4.0, "RES002": 2.0}),
    )
    try:
        requests = coordinator.run_coordinator_pass()
        assert len(requests) == 1
        assert requests[0]["resource_id"] == "RES001"

        snapshot = fetch_one(
            allocation_environment,
            """
            SELECT available_resource_count, nearest_eligible_distance_km
            FROM ML_Feature_Snapshots
            WHERE requirement_unit_id = ?
            """,
            ("UNIT001",),
        )
        assert snapshot is not None
        assert snapshot["available_resource_count"] == 1
        assert snapshot["nearest_eligible_distance_km"] == pytest.approx(4.0)
    finally:
        coordinator.close()


def test_unresolved_emergency_is_not_dispatched(allocation_environment):
    connection = sqlite3.connect(allocation_environment)
    connection.execute(
        "UPDATE Emergencies SET location_resolved = 0 WHERE emergency_id = ?",
        ("EMG001",),
    )
    connection.commit()
    connection.close()

    coordinator = AllocationCoordinator(
        allocation_environment,
        FakeRoadEngine({"RES001": 4.0, "RES002": 2.0}),
    )
    try:
        assert coordinator.run_coordinator_pass() == []

        unit = fetch_one(
            allocation_environment,
            "SELECT status FROM Requirement_Units WHERE requirement_unit_id = ?",
            ("UNIT001",),
        )
        assert unit["status"] == "PENDING"

        allocation_count = fetch_one(
            allocation_environment,
            "SELECT COUNT(*) AS count FROM Allocations",
        )
        assert allocation_count["count"] == 0

        snapshot_count = fetch_one(
            allocation_environment,
            """
            SELECT COUNT(*) AS count
            FROM ML_Feature_Snapshots
            WHERE requirement_unit_id = ?
            """,
            ("UNIT001",),
        )
        assert snapshot_count["count"] == 0
    finally:
        coordinator.close()


def test_organization_accepts_allocation(allocation_environment, coordinator):
    request = coordinator.run_coordinator_pass()[0]

    result = coordinator.organization_response(
        request["allocation_id"], "ORG001", accept=True
    )

    assert result["ok"] is True
    assert result["code"] == "ACCEPTED"

    allocation = fetch_one(
        allocation_environment,
        "SELECT status, response_status, dispatched_at FROM Allocations WHERE allocation_id = ?",
        (request["allocation_id"],),
    )
    unit = fetch_one(
        allocation_environment,
        "SELECT status, pending_since, expires_at FROM Requirement_Units WHERE requirement_unit_id = 'UNIT001'",
    )
    resource = fetch_one(
        allocation_environment,
        "SELECT status FROM Resources WHERE resource_id = ?",
        (request["resource_id"],),
    )

    assert allocation["status"] == "DISPATCHED"
    assert allocation["response_status"] == "ACCEPTED"
    assert allocation["dispatched_at"] is not None
    assert unit["status"] == "DISPATCHED"
    assert unit["pending_since"] is None
    assert unit["expires_at"] is None
    assert resource["status"] == "DISPATCHED"


def test_organization_rejects_allocation(allocation_environment, coordinator):
    request = coordinator.run_coordinator_pass()[0]

    result = coordinator.organization_response(
        request["allocation_id"],
        "ORG001",
        accept=False,
        reason="Vehicle unavailable",
    )

    assert result["ok"] is True
    assert result["code"] == "REJECTED"

    allocation = fetch_one(
        allocation_environment,
        "SELECT status, response_status, rejection_reason FROM Allocations WHERE allocation_id = ?",
        (request["allocation_id"],),
    )
    unit = fetch_one(
        allocation_environment,
        "SELECT status FROM Requirement_Units WHERE requirement_unit_id = 'UNIT001'",
    )
    resource = fetch_one(
        allocation_environment,
        "SELECT status FROM Resources WHERE resource_id = ?",
        (request["resource_id"],),
    )

    assert allocation["status"] == "CLOSED"
    assert allocation["response_status"] == "REJECTED"
    assert allocation["rejection_reason"] == "Vehicle unavailable"
    assert unit["status"] == "REQUESTED"
    assert resource["status"] == "AVAILABLE"

    replacement = fetch_one(
        allocation_environment,
        """
        SELECT allocation_id, resource_id, status, response_status
        FROM Allocations
        WHERE requirement_unit_id = 'UNIT001'
          AND allocation_id != ?
          AND status = 'REQUESTED'
        """,
        (request["allocation_id"],),
    )
    assert replacement is not None
    assert replacement["resource_id"] != request["resource_id"]
    assert replacement["response_status"] == "PENDING"


def test_completed_allocation_fulfils_unit(allocation_environment, coordinator):
    request = coordinator.run_coordinator_pass()[0]
    accepted = coordinator.organization_response(
        request["allocation_id"], "ORG001", accept=True
    )
    assert accepted["ok"] is True

    result = coordinator.complete_allocation(
        request["allocation_id"], "ORG001"
    )

    assert result["ok"] is True
    assert result["code"] == "COMPLETED"

    allocation = fetch_one(
        allocation_environment,
        "SELECT status, completed_at, returned_at FROM Allocations WHERE allocation_id = ?",
        (request["allocation_id"],),
    )
    unit = fetch_one(
        allocation_environment,
        "SELECT status FROM Requirement_Units WHERE requirement_unit_id = 'UNIT001'",
    )
    resource = fetch_one(
        allocation_environment,
        "SELECT status FROM Resources WHERE resource_id = ?",
        (request["resource_id"],),
    )
    emergency = fetch_one(
        allocation_environment,
        "SELECT status FROM Emergencies WHERE emergency_id = 'EMG001'",
    )

    assert allocation["status"] == "COMPLETED"
    assert allocation["completed_at"] is not None
    assert allocation["returned_at"] is not None
    assert unit["status"] == "FULFILLED"
    assert resource["status"] == "AVAILABLE"
    assert emergency["status"] == "COMPLETED"


def test_failed_allocation_returns_unit_to_pending(allocation_environment, coordinator):
    request = coordinator.run_coordinator_pass()[0]
    accepted = coordinator.organization_response(
        request["allocation_id"], "ORG001", accept=True
    )
    assert accepted["ok"] is True

    result = coordinator.fail_allocation(
        request["allocation_id"], "ORG001", "Vehicle breakdown"
    )

    assert result["ok"] is True
    assert result["code"] == "FAILED"

    allocation = fetch_one(
        allocation_environment,
        "SELECT status, returned_at FROM Allocations WHERE allocation_id = ?",
        (request["allocation_id"],),
    )
    unit = fetch_one(
        allocation_environment,
        "SELECT status, pending_since, expires_at FROM Requirement_Units WHERE requirement_unit_id = 'UNIT001'",
    )
    resource = fetch_one(
        allocation_environment,
        "SELECT status FROM Resources WHERE resource_id = ?",
        (request["resource_id"],),
    )
    replacement = fetch_one(
        allocation_environment,
        """
        SELECT allocation_id, resource_id, status, response_status
        FROM Allocations
        WHERE requirement_unit_id = 'UNIT001'
          AND allocation_id != ?
        ORDER BY requested_at DESC
        LIMIT 1
        """,
        (request["allocation_id"],),
    )

    assert allocation["status"] == "FAILED"
    assert allocation["returned_at"] is not None
    assert unit["status"] == "REQUESTED"
    assert unit["pending_since"] is None
    assert unit["expires_at"] is None
    assert resource["status"] == "UNAVAILABLE"
    assert replacement is not None
    assert replacement["resource_id"] != request["resource_id"]
    assert replacement["status"] == "REQUESTED"
    assert replacement["response_status"] == "PENDING"


def test_expired_request_times_out_and_releases_resource(
    allocation_environment, coordinator
):
    request = coordinator.run_coordinator_pass()[0]
    future = datetime.now(timezone.utc) + timedelta(seconds=31)

    changed = coordinator.process_allocation_timeouts(now=future)

    assert changed == 1

    allocation = fetch_one(
        allocation_environment,
        "SELECT status, response_status, response_at FROM Allocations WHERE allocation_id = ?",
        (request["allocation_id"],),
    )
    unit = fetch_one(
        allocation_environment,
        "SELECT status FROM Requirement_Units WHERE requirement_unit_id = 'UNIT001'",
    )
    resource = fetch_one(
        allocation_environment,
        "SELECT status FROM Resources WHERE resource_id = ?",
        (request["resource_id"],),
    )

    assert allocation["status"] == "CLOSED"
    assert allocation["response_status"] == "TIMEOUT"
    assert allocation["response_at"] is not None
    assert unit["status"] == "REQUESTED"
    assert resource["status"] == "AVAILABLE"

    replacement = fetch_one(
        allocation_environment,
        """
        SELECT allocation_id, resource_id, status, response_status
        FROM Allocations
        WHERE requirement_unit_id = 'UNIT001'
          AND allocation_id != ?
          AND status = 'REQUESTED'
        """,
        (request["allocation_id"],),
    )
    assert replacement is not None
    assert replacement["resource_id"] != request["resource_id"]
    assert replacement["response_status"] == "PENDING"

def test_wrong_organization_cannot_respond_to_allocation(
    allocation_environment, coordinator
):
    request = coordinator.run_coordinator_pass()[0]

    result = coordinator.organization_response(
        request["allocation_id"], "OTHER_ORG", accept=True
    )

    assert result["ok"] is False

    allocation = fetch_one(
        allocation_environment,
        "SELECT status, response_status FROM Allocations WHERE allocation_id = ?",
        (request["allocation_id"],),
    )
    unit = fetch_one(
        allocation_environment,
        "SELECT status FROM Requirement_Units WHERE requirement_unit_id = 'UNIT001'",
    )
    resource = fetch_one(
        allocation_environment,
        "SELECT status FROM Resources WHERE resource_id = ?",
        (request["resource_id"],),
    )

    assert allocation["status"] == "REQUESTED"
    assert allocation["response_status"] == "PENDING"
    assert unit["status"] == "REQUESTED"
    assert resource["status"] == "REQUESTED"


def test_duplicate_organization_response_is_rejected(
    allocation_environment, coordinator
):
    request = coordinator.run_coordinator_pass()[0]

    first = coordinator.organization_response(
        request["allocation_id"], "ORG001", accept=True
    )
    assert first["ok"] is True

    second = coordinator.organization_response(
        request["allocation_id"],
        "ORG001",
        accept=False,
        reason="Late duplicate rejection",
    )

    assert second["ok"] is False

    allocation = fetch_one(
        allocation_environment,
        "SELECT status, response_status FROM Allocations WHERE allocation_id = ?",
        (request["allocation_id"],),
    )
    unit = fetch_one(
        allocation_environment,
        "SELECT status FROM Requirement_Units WHERE requirement_unit_id = 'UNIT001'",
    )
    resource = fetch_one(
        allocation_environment,
        "SELECT status FROM Resources WHERE resource_id = ?",
        (request["resource_id"],),
    )

    assert allocation["status"] == "DISPATCHED"
    assert allocation["response_status"] == "ACCEPTED"
    assert unit["status"] == "DISPATCHED"
    assert resource["status"] == "DISPATCHED"


def test_unaccepted_allocation_cannot_be_completed(
    allocation_environment, coordinator
):
    request = coordinator.run_coordinator_pass()[0]

    result = coordinator.complete_allocation(
        request["allocation_id"], "ORG001"
    )

    assert result["ok"] is False

    allocation = fetch_one(
        allocation_environment,
        "SELECT status, completed_at FROM Allocations WHERE allocation_id = ?",
        (request["allocation_id"],),
    )
    unit = fetch_one(
        allocation_environment,
        "SELECT status FROM Requirement_Units WHERE requirement_unit_id = 'UNIT001'",
    )
    resource = fetch_one(
        allocation_environment,
        "SELECT status FROM Resources WHERE resource_id = ?",
        (request["resource_id"],),
    )

    assert allocation["status"] == "REQUESTED"
    assert allocation["completed_at"] is None
    assert unit["status"] == "REQUESTED"
    assert resource["status"] == "REQUESTED"


def test_repeated_timeout_does_not_repeat_transition(
    allocation_environment, coordinator
):
    request = coordinator.run_coordinator_pass()[0]
    future = datetime.now(timezone.utc) + timedelta(seconds=31)

    first_count = coordinator.process_allocation_timeouts(now=future)
    second_count = coordinator.process_allocation_timeouts(now=future)

    assert first_count == 1
    assert second_count == 0

    allocation = fetch_one(
        allocation_environment,
        "SELECT status, response_status, response_at FROM Allocations WHERE allocation_id = ?",
        (request["allocation_id"],),
    )
    unit = fetch_one(
        allocation_environment,
        "SELECT status FROM Requirement_Units WHERE requirement_unit_id = 'UNIT001'",
    )
    resource = fetch_one(
        allocation_environment,
        "SELECT status FROM Resources WHERE resource_id = ?",
        (request["resource_id"],),
    )

    assert allocation["status"] == "CLOSED"
    assert allocation["response_status"] == "TIMEOUT"
    assert allocation["response_at"] is not None
    assert unit["status"] == "REQUESTED"
    assert resource["status"] == "AVAILABLE"

    replacement = fetch_one(
        allocation_environment,
        """
        SELECT allocation_id, resource_id, status, response_status
        FROM Allocations
        WHERE requirement_unit_id = 'UNIT001'
          AND allocation_id != ?
          AND status = 'REQUESTED'
        """,
        (request["allocation_id"],),
    )
    assert replacement is not None
    assert replacement["resource_id"] != request["resource_id"]
    assert replacement["response_status"] == "PENDING"

def test_rejection_preserves_pending_episode_and_tries_next_resource(
    allocation_environment, coordinator
):
    pending_since = datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    expires_at = (
        datetime.now(timezone.utc) + timedelta(minutes=5)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")

    connection = sqlite3.connect(allocation_environment)
    try:
        connection.execute(
            """
            UPDATE Requirement_Units
            SET status = 'PENDING',
                pending_since = ?,
                expires_at = ?,
                episode_count = 1
            WHERE requirement_unit_id = 'UNIT001'
            """,
            (pending_since, expires_at),
        )
        connection.commit()
    finally:
        connection.close()

    first_request = coordinator.run_coordinator_pass()[0]

    rejected = coordinator.organization_response(
        first_request["allocation_id"],
        "ORG001",
        accept=False,
        reason="Vehicle unavailable",
    )
    assert rejected["ok"] is True

    unit = fetch_one(
        allocation_environment,
        """
        SELECT status, pending_since, expires_at, episode_count
        FROM Requirement_Units
        WHERE requirement_unit_id = 'UNIT001'
        """,
    )

    assert unit["status"] == "REQUESTED"
    assert unit["pending_since"] == pending_since
    assert unit["expires_at"] == expires_at
    assert unit["episode_count"] == 1

    second_request = fetch_one(
        allocation_environment,
        """
        SELECT allocation_id, resource_id, status, response_status
        FROM Allocations
        WHERE requirement_unit_id = 'UNIT001'
          AND allocation_id != ?
          AND status = 'REQUESTED'
        """,
        (first_request["allocation_id"],),
    )
    assert second_request is not None
    assert second_request["resource_id"] != first_request["resource_id"]
    assert second_request["response_status"] == "PENDING"
    assert coordinator.run_coordinator_pass() == []

    unit_after_retry = fetch_one(
        allocation_environment,
        """
        SELECT status, pending_since, expires_at, episode_count
        FROM Requirement_Units
        WHERE requirement_unit_id = 'UNIT001'
        """,
    )

    assert unit_after_retry["status"] == "REQUESTED"
    assert unit_after_retry["pending_since"] == pending_since
    assert unit_after_retry["expires_at"] == expires_at
    assert unit_after_retry["episode_count"] == 1

def test_complete_pending_lifecycle_through_unfulfilled(
    allocation_environment, coordinator
):
    # 1. No routable resources: start the first pending episode.
    coordinator.road_engine.distances = {}

    requests = coordinator.run_coordinator_pass()
    assert requests == []

    unit = fetch_one(
        allocation_environment,
        """
        SELECT status, pending_since, expires_at, episode_count
        FROM Requirement_Units
        WHERE requirement_unit_id = 'UNIT001'
        """,
    )

    assert unit["status"] == "PENDING"
    assert unit["pending_since"] is not None
    assert unit["expires_at"] is not None
    assert unit["episode_count"] == 1

    original_pending_since = unit["pending_since"]
    original_expires_at = unit["expires_at"]

    # 2. Make both resources routable. The nearest is requested first.
    coordinator.road_engine.distances = {
        "RES001": 4.0,
        "RES002": 2.0,
    }

    first_request = coordinator.run_coordinator_pass()
    assert len(first_request) == 1
    assert first_request[0]["resource_id"] == "RES002"

    # 3. Organization rejects the first resource.
    result = coordinator.organization_response(
        first_request[0]["allocation_id"],
        "ORG001",
        accept=False,
        reason="Vehicle unavailable",
    )
    assert result["ok"] is True

    unit = fetch_one(
        allocation_environment,
        """
        SELECT status, pending_since, expires_at, episode_count
        FROM Requirement_Units
        WHERE requirement_unit_id = 'UNIT001'
        """,
    )

    assert unit["status"] == "REQUESTED"
    assert unit["pending_since"] == original_pending_since
    assert unit["expires_at"] == original_expires_at
    assert unit["episode_count"] == 1

    # 4. The second resource was requested immediately; reject it too.
    second_request = fetch_one(
        allocation_environment,
        """
        SELECT allocation_id, resource_id
        FROM Allocations
        WHERE requirement_unit_id = 'UNIT001'
          AND allocation_id != ?
          AND status = 'REQUESTED'
        """,
        (first_request[0]["allocation_id"],),
    )
    assert second_request is not None
    assert second_request["resource_id"] == "RES001"
    assert coordinator.run_coordinator_pass() == []

    result = coordinator.organization_response(
        second_request["allocation_id"],
        "ORG001",
        accept=False,
        reason="Vehicle unavailable",
    )
    assert result["ok"] is True

    # Both resources have now been attempted and are excluded.
    assert coordinator.run_coordinator_pass() == []

    unit = fetch_one(
        allocation_environment,
        """
        SELECT status, pending_since, expires_at, episode_count
        FROM Requirement_Units
        WHERE requirement_unit_id = 'UNIT001'
        """,
    )

    assert unit["status"] == "PENDING"
    assert unit["pending_since"] == original_pending_since
    assert unit["expires_at"] == original_expires_at
    assert unit["episode_count"] == 1

    # 5. Expire the first episode after a fresh evaluation finds no candidate.
    earlier = (
        datetime.now(timezone.utc) - timedelta(minutes=10)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")
    past = (
        datetime.now(timezone.utc) - timedelta(seconds=5)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")

    connection = sqlite3.connect(allocation_environment)
    try:
        connection.execute(
            """
            UPDATE Requirement_Units
            SET pending_since = ?, expires_at = ?
            WHERE requirement_unit_id = 'UNIT001'
            """,
            (earlier, past),
        )
        connection.commit()
    finally:
        connection.close()

    assert coordinator.run_coordinator_pass() == []

    unit = fetch_one(
        allocation_environment,
        """
        SELECT status, pending_since, expires_at, episode_count
        FROM Requirement_Units
        WHERE requirement_unit_id = 'UNIT001'
        """,
    )

    assert unit["status"] == "PENDING"
    assert unit["pending_since"] is None
    assert unit["expires_at"] is None
    assert unit["episode_count"] == 1

    # The next pass starts the second bounded pending episode.
    assert coordinator.run_coordinator_pass() == []

    unit = fetch_one(
        allocation_environment,
        """
        SELECT status, pending_since, expires_at, episode_count
        FROM Requirement_Units
        WHERE requirement_unit_id = 'UNIT001'
        """,
    )

    assert unit["status"] == "PENDING"
    assert unit["pending_since"] is not None
    assert unit["expires_at"] is not None
    assert unit["episode_count"] == 2

    # Expiring the second episode without a candidate makes it UNFULFILLED.
    connection = sqlite3.connect(allocation_environment)
    try:
        connection.execute(
            """
            UPDATE Requirement_Units
            SET pending_since = ?, expires_at = ?
            WHERE requirement_unit_id = 'UNIT001'
            """,
            (earlier, past),
        )
        connection.commit()
    finally:
        connection.close()

    assert coordinator.run_coordinator_pass() == []

    unit = fetch_one(
        allocation_environment,
        """
        SELECT status, pending_since, expires_at, episode_count
        FROM Requirement_Units
        WHERE requirement_unit_id = 'UNIT001'
        """,
    )
    emergency = fetch_one(
        allocation_environment,
        "SELECT status FROM Emergencies WHERE emergency_id = 'EMG001'",
    )

    assert unit["status"] == "UNFULFILLED"
    assert unit["pending_since"] is None
    assert unit["expires_at"] is None
    assert unit["episode_count"] == 2
    assert emergency["status"] == "UNFULFILLED"


def test_late_accept_returns_stable_expired_result(
    allocation_environment, coordinator
):
    request = coordinator.run_coordinator_pass()[0]
    future = datetime.now(timezone.utc) + timedelta(seconds=31)

    first = coordinator.organization_response(
        request["allocation_id"], "ORG001", accept=True, now=future
    )
    second = coordinator.organization_response(
        request["allocation_id"], "ORG001", accept=True, now=future
    )

    assert first["ok"] is False
    assert first["code"] == "ALLOCATION_EXPIRED"
    assert second["ok"] is False
    assert second["code"] == "ALLOCATION_EXPIRED"

    allocation = fetch_one(
        allocation_environment,
        """
        SELECT status, response_status
        FROM Allocations WHERE allocation_id = ?
        """,
        (request["allocation_id"],),
    )
    resource = fetch_one(
        allocation_environment,
        "SELECT status FROM Resources WHERE resource_id = ?",
        (request["resource_id"],),
    )
    events = fetch_one(
        allocation_environment,
        """
        SELECT COUNT(*) AS count
        FROM Allocation_Decision_Events
        WHERE requirement_unit_id = ?
          AND event_type = 'TIMEOUT'
        """,
        ("UNIT001",),
    )

    assert allocation["status"] == "CLOSED"
    assert allocation["response_status"] == "TIMEOUT"
    assert resource["status"] == "AVAILABLE"
    assert events["count"] == 1
