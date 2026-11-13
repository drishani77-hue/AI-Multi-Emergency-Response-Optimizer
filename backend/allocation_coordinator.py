"""Central allocation coordinator for ResQTech.

SQLite is authoritative. Native C heaps are rebuilt as derived priority indexes;
the road engine is used only to rank resources with valid road routes.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from functools import wraps
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from backend.db import connect_database
from backend.priority_heap import PriorityHeap

logger = logging.getLogger(__name__)

RESOURCE_TYPES = (
    "AMBULANCE",
    "FIRE_VEHICLE",
    "POLICE_UNIT",
    "RESCUE_VEHICLE",
)

DEFAULT_RESPONSE_TIMEOUT_SECONDS = 30
DEFAULT_PENDING_EPISODE_SECONDS = 300
DEFAULT_MAX_PENDING_EPISODES = 2

TERMINAL_UNIT_STATES = ("FULFILLED", "UNFULFILLED", "CANCELLED")
ACTIVE_UNIT_STATES = ("PENDING", "REQUESTED", "DISPATCHED")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _stamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _synchronized(method):
    """Serialize public coordinator operations within this process."""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapped


class AllocationCoordinator:
    """Coordinates one-candidate-at-a-time resource allocation."""

    def __init__(
        self,
        database_path: str | Path,
        road_engine,
        *,
        response_timeout_seconds: int = DEFAULT_RESPONSE_TIMEOUT_SECONDS,
        pending_episode_seconds: int = DEFAULT_PENDING_EPISODE_SECONDS,
        max_pending_episodes: int = DEFAULT_MAX_PENDING_EPISODES,
        heap_factory: Callable[[str], PriorityHeap] = PriorityHeap,
    ) -> None:
        if response_timeout_seconds <= 0:
            raise ValueError("response_timeout_seconds must be positive.")
        if pending_episode_seconds <= 0:
            raise ValueError("pending_episode_seconds must be positive.")
        if max_pending_episodes <= 0:
            raise ValueError("max_pending_episodes must be positive.")

        self.database_path = str(database_path)
        self.road_engine = road_engine
        self.response_timeout_seconds = int(response_timeout_seconds)
        self.pending_episode_seconds = int(pending_episode_seconds)
        self.max_pending_episodes = int(max_pending_episodes)
        self._lock = threading.RLock()
        self._heaps = {kind: heap_factory(kind) for kind in RESOURCE_TYPES}
        self._closed = False

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            for heap in self._heaps.values():
                heap.close()
            self._closed = True

    def _connect(self):
        if self._closed:
            raise RuntimeError("AllocationCoordinator is closed.")
        return connect_database(self.database_path)

    @staticmethod
    def _event(
        connection: sqlite3.Connection,
        emergency_id: str,
        unit_id: str,
        event_type: str,
        *,
        resource_id: str | None = None,
        distance_km: float | None = None,
        reason: str | None = None,
        event_time: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO Allocation_Decision_Events
                (event_id, emergency_id, requirement_unit_id, resource_id,
                 event_type, event_time, distance_km, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                emergency_id,
                unit_id,
                resource_id,
                event_type,
                event_time,
                distance_km,
                reason,
            ),
        )

    @staticmethod
    def _recompute_statuses(
        connection: sqlite3.Connection,
        emergency_id: str,
    ) -> None:
        groups = connection.execute(
            """
            SELECT requirement_group_id
            FROM Requirement_Groups
            WHERE emergency_id = ?
            """,
            (emergency_id,),
        ).fetchall()

        for group in groups:
            states = [
                row["status"]
                for row in connection.execute(
                    """
                    SELECT status FROM Requirement_Units
                    WHERE requirement_group_id = ?
                    """,
                    (group["requirement_group_id"],),
                ).fetchall()
            ]
            if not states:
                group_status = "PENDING"
            elif all(state == "FULFILLED" for state in states):
                group_status = "COMPLETED"
            elif all(state in TERMINAL_UNIT_STATES for state in states):
                group_status = (
                    "UNFULFILLED"
                    if "UNFULFILLED" in states
                    else "COMPLETED"
                )
            elif all(state in ("DISPATCHED", "FULFILLED") for state in states):
                group_status = "FULLY_ALLOCATED"
            elif any(state in ("DISPATCHED", "FULFILLED") for state in states):
                group_status = "PARTIALLY_ALLOCATED"
            else:
                group_status = "PENDING"

            connection.execute(
                """
                UPDATE Requirement_Groups
                SET status = ?
                WHERE requirement_group_id = ?
                """,
                (group_status, group["requirement_group_id"]),
            )

        group_states = [
            row["status"]
            for row in connection.execute(
                """
                SELECT status FROM Requirement_Groups
                WHERE emergency_id = ?
                """,
                (emergency_id,),
            ).fetchall()
        ]

        if not group_states:
            emergency_status = "PENDING"
        elif all(state == "COMPLETED" for state in group_states):
            emergency_status = "COMPLETED"
        elif all(state in ("COMPLETED", "UNFULFILLED") for state in group_states):
            emergency_status = (
                "UNFULFILLED"
                if "UNFULFILLED" in group_states
                else "COMPLETED"
            )
        elif all(state in ("FULLY_ALLOCATED", "COMPLETED") for state in group_states):
            emergency_status = "FULLY_ALLOCATED"
        elif any(
            state in ("PARTIALLY_ALLOCATED", "FULLY_ALLOCATED", "COMPLETED")
            for state in group_states
        ):
            emergency_status = "PARTIALLY_ALLOCATED"
        else:
            emergency_status = "PENDING"

        connection.execute(
            "UPDATE Emergencies SET status = ? WHERE emergency_id = ?",
            (emergency_status, emergency_id),
        )

    @staticmethod
    def _assert_invariants(
        connection: sqlite3.Connection,
        emergency_id: str,
    ) -> None:
        bad_units = connection.execute(
            """
            SELECT ru.requirement_unit_id
            FROM Requirement_Units ru
            LEFT JOIN Allocations a
              ON a.requirement_unit_id = ru.requirement_unit_id
             AND a.status = 'REQUESTED'
            WHERE ru.status = 'REQUESTED'
              AND (SELECT COUNT(*) FROM Allocations x
                   WHERE x.requirement_unit_id = ru.requirement_unit_id
                     AND x.status = 'REQUESTED') <> 1
              AND ru.requirement_group_id IN
                  (SELECT requirement_group_id FROM Requirement_Groups
                   WHERE emergency_id = ?)
            """,
            (emergency_id,),
        ).fetchall()
        if bad_units:
            raise RuntimeError(
                "Invariant violation: REQUESTED unit must have exactly one "
                "REQUESTED allocation."
            )

        bad_resources = connection.execute(
            """
            SELECT r.resource_id
            FROM Resources r
            WHERE r.status = 'REQUESTED'
              AND NOT EXISTS (
                  SELECT 1 FROM Allocations a
                  WHERE a.resource_id = r.resource_id
                    AND a.status = 'REQUESTED'
              )
              AND EXISTS (
                  SELECT 1 FROM Allocations a
                  WHERE a.resource_id = r.resource_id
                    AND a.emergency_id = ?
              )
            """,
            (emergency_id,),
        ).fetchall()
        if bad_resources:
            raise RuntimeError(
                "Invariant violation: REQUESTED resource has no open request."
            )

    def _rebuild_heaps(self) -> None:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT ru.requirement_unit_id, e.emergency_id, ru.resource_type,
                       e.severity, e.reported_at
                FROM Requirement_Units ru
                JOIN Requirement_Groups rg
                  ON rg.requirement_group_id = ru.requirement_group_id
                JOIN Emergencies e ON e.emergency_id = rg.emergency_id
                WHERE ru.status = 'PENDING'
                  AND e.location_resolved = 1
                  AND e.location_id IS NOT NULL
                """
            ).fetchall()
        finally:
            connection.close()

        with self._lock:
            for heap in self._heaps.values():
                heap.clear()
            for row in rows:
                self._heaps[row["resource_type"]].push(
                    requirement_unit_id=row["requirement_unit_id"],
                    emergency_id=row["emergency_id"],
                    severity=row["severity"],
                    reported_at=row["reported_at"],
                )


    def _capture_ml_feature_snapshot(
        self,
        connection: sqlite3.Connection,
        unit_id: str,
        emergency_id: str,
        resource_type: str,
        now: datetime,
        ranked: list[dict],
    ) -> None:
        """Persist the first decision-time feature snapshot for a requirement unit."""
        emergency = connection.execute(
            """
            SELECT e.emergency_type, e.severity, e.reported_at,
                   e.data_source, l.locality
            FROM Emergencies e
            LEFT JOIN Locations l ON l.location_id = e.location_id
            WHERE e.emergency_id = ?
            """,
            (emergency_id,),
        ).fetchone()

        if emergency is None:
            return

        available_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM Resources r
            JOIN Organizations o ON o.organization_id = r.organization_id
            JOIN Locations l ON l.location_id = r.base_location_id
            WHERE r.resource_type = ?
              AND r.status = 'AVAILABLE'
              AND o.status = 'ACTIVE'
              AND r.base_location_id IS NOT NULL
              AND l.road_node_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM Allocations a
                  WHERE a.requirement_unit_id = ?
                    AND a.resource_id = r.resource_id
              )
            """,
            (resource_type, unit_id),
        ).fetchone()[0]

        active_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM Emergencies
            WHERE status IN (
                'PENDING', 'PARTIALLY_ALLOCATED', 'FULLY_ALLOCATED'
            )
            """
        ).fetchone()[0]

        pending_units = connection.execute(
            """
            SELECT ru.requirement_unit_id, rg.emergency_id,
                   e.severity, e.reported_at
            FROM Requirement_Units ru
            JOIN Requirement_Groups rg
              ON rg.requirement_group_id = ru.requirement_group_id
            JOIN Emergencies e ON e.emergency_id = rg.emergency_id
            WHERE ru.status = 'PENDING'
              AND ru.resource_type = ?
              AND e.location_resolved = 1
              AND e.location_id IS NOT NULL
            """,
            (resource_type,),
        ).fetchall()

        severity_rank = {
            "LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4
        }
        current_key = (
            -severity_rank[emergency["severity"]],
            emergency["reported_at"],
            unit_id,
        )

        higher_priority_count = 0
        for pending in pending_units:
            if pending["emergency_id"] == emergency_id:
                continue

            other_key = (
                -severity_rank[pending["severity"]],
                pending["reported_at"],
                pending["requirement_unit_id"],
            )
            if other_key < current_key:
                higher_priority_count += 1

        decision_time = now.astimezone(timezone.utc)
        nearest_distance = (
            ranked[0]["distance_km"] if ranked else None
        )

        connection.execute(
            """
            INSERT INTO ML_Feature_Snapshots (
                snapshot_id, requirement_unit_id, snapshot_at,
                available_resource_count, active_emergency_count,
                higher_priority_pending_count,
                nearest_eligible_distance_km, time_of_day, day_of_week,
                emergency_type, severity, resource_type, locality, data_source
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(requirement_unit_id) DO NOTHING
            """,
            (
                str(uuid.uuid4()),
                unit_id,
                _stamp(decision_time),
                available_count,
                active_count,
                higher_priority_count,
                nearest_distance,
                decision_time.hour,
                decision_time.weekday(),
                emergency["emergency_type"],
                emergency["severity"],
                resource_type,
                emergency["locality"],
                emergency["data_source"],
            ),
        )

    def _rank_candidates(
        self,
        connection: sqlite3.Connection,
        emergency_id: str,
        resource_type: str,
        unit_id: str,
        now_text: str,
    ) -> list[dict]:
        emergency = connection.execute(
            """
            SELECT l.road_node_id
            FROM Emergencies e
            JOIN Locations l ON l.location_id = e.location_id
            WHERE e.emergency_id = ?
              AND e.location_resolved = 1
            """,
            (emergency_id,),
        ).fetchone()
        if emergency is None or emergency["road_node_id"] is None:
            return []

        try:
            emergency_node = int(emergency["road_node_id"])
        except (TypeError, ValueError):
            logger.warning("Invalid emergency road_node_id for %s", emergency_id)
            return []

        candidates = connection.execute(
            """
            SELECT r.resource_id, l.road_node_id AS base_osm_id
            FROM Resources r
            JOIN Organizations o ON o.organization_id = r.organization_id
            JOIN Locations l ON l.location_id = r.base_location_id
            WHERE r.resource_type = ?
              AND r.status = 'AVAILABLE'
              AND o.status = 'ACTIVE'
              AND r.base_location_id IS NOT NULL
              AND l.road_node_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM Allocations a
                  WHERE a.requirement_unit_id = ?
                    AND a.resource_id = r.resource_id
              )
            ORDER BY r.resource_id
            """,
            (resource_type, unit_id),
        ).fetchall()

        road_candidates = []
        for candidate in candidates:
            try:
                node_id = int(candidate["base_osm_id"])
            except (TypeError, ValueError):
                continue
            road_candidates.append(
                {"resource_id": candidate["resource_id"], "base_osm_id": node_id}
            )

        if not road_candidates:
            return []

        ranked = self.road_engine.rank_resources(emergency_node, road_candidates)
        ranked_ids = {item["resource_id"] for item in ranked}
        for candidate in road_candidates:
            if candidate["resource_id"] not in ranked_ids:
                self._event(
                    connection,
                    emergency_id,
                    unit_id,
                    "NO_ROUTE",
                    resource_id=candidate["resource_id"],
                    reason="No valid road route from emergency to resource base.",
                    event_time=now_text,
                )
        return ranked

    def _reserve_candidate(
        self,
        unit_id: str,
        emergency_id: str,
        resource_type: str,
        ranked: list[dict],
        now: datetime,
    ) -> dict | None:
        for candidate in ranked:
            now_text = _stamp(now)
            deadline_text = _stamp(
                now + timedelta(seconds=self.response_timeout_seconds)
            )
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                unit = connection.execute(
                    """
                    SELECT ru.status, ru.requirement_group_id, rg.emergency_id
                    FROM Requirement_Units ru
                    JOIN Requirement_Groups rg
                      ON rg.requirement_group_id = ru.requirement_group_id
                    WHERE ru.requirement_unit_id = ?
                    """,
                    (unit_id,),
                ).fetchone()
                resource = connection.execute(
                    """
                    SELECT r.status, r.resource_type, o.status AS organization_status
                    FROM Resources r
                    JOIN Organizations o ON o.organization_id = r.organization_id
                    WHERE r.resource_id = ?
                    """,
                    (candidate["resource_id"],),
                ).fetchone()

                if (
                    unit is None
                    or unit["status"] != "PENDING"
                    or unit["emergency_id"] != emergency_id
                    or resource is None
                    or resource["status"] != "AVAILABLE"
                    or resource["organization_status"] != "ACTIVE"
                    or resource["resource_type"] != resource_type
                ):
                    connection.rollback()
                    continue

                already_attempted = connection.execute(
                    """
                    SELECT 1 FROM Allocations
                    WHERE requirement_unit_id = ? AND resource_id = ?
                    LIMIT 1
                    """,
                    (unit_id, candidate["resource_id"]),
                ).fetchone()
                if already_attempted:
                    connection.rollback()
                    continue

                allocation_id = str(uuid.uuid4())
                connection.execute(
                    """
                    INSERT INTO Allocations
                        (allocation_id, emergency_id, requirement_unit_id,
                         resource_id, requested_at, deadline_at,
                         response_status, distance_km, status)
                    VALUES (?, ?, ?, ?, ?, ?, 'PENDING', ?, 'REQUESTED')
                    """,
                    (
                        allocation_id,
                        emergency_id,
                        unit_id,
                        candidate["resource_id"],
                        now_text,
                        deadline_text,
                        candidate["distance_km"],
                    ),
                )
                connection.execute(
                    """
                    UPDATE Resources
                    SET status = 'REQUESTED', last_updated = ?
                    WHERE resource_id = ?
                    """,
                    (now_text, candidate["resource_id"]),
                )
                connection.execute(
                    """
                    UPDATE Requirement_Units
                    SET status = 'REQUESTED'
                    WHERE requirement_unit_id = ?
                    """,
                    (unit_id,),
                )
                self._event(
                    connection,
                    emergency_id,
                    unit_id,
                    "ALLOCATION_REQUESTED",
                    resource_id=candidate["resource_id"],
                    distance_km=candidate["distance_km"],
                    event_time=now_text,
                )
                self._recompute_statuses(connection, emergency_id)
                self._assert_invariants(connection, emergency_id)
                connection.commit()
                return {
                    "allocation_id": allocation_id,
                    "requirement_unit_id": unit_id,
                    "emergency_id": emergency_id,
                    "resource_id": candidate["resource_id"],
                    "distance_km": candidate["distance_km"],
                    "deadline_at": deadline_text,
                }
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
            finally:
                connection.close()
        return None

    def _start_pending_episode(
        self,
        unit_id: str,
        emergency_id: str,
        now: datetime,
    ) -> bool:
        now_text = _stamp(now)
        expires_text = _stamp(
            now + timedelta(seconds=self.pending_episode_seconds)
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            unit = connection.execute(
                """
                SELECT status, pending_since, episode_count
                FROM Requirement_Units
                WHERE requirement_unit_id = ?
                """,
                (unit_id,),
            ).fetchone()
            if unit is None or unit["status"] != "PENDING":
                connection.rollback()
                return False

            if unit["pending_since"] is not None:
                connection.rollback()
                return False

            if unit["episode_count"] >= self.max_pending_episodes:
                connection.execute(
                    """
                    UPDATE Requirement_Units
                    SET status = 'UNFULFILLED'
                    WHERE requirement_unit_id = ?
                    """,
                    (unit_id,),
                )
                self._event(
                    connection,
                    emergency_id,
                    unit_id,
                    "UNFULFILLED",
                    reason="Maximum pending episodes reached.",
                    event_time=now_text,
                )
            else:
                connection.execute(
                    """
                    UPDATE Requirement_Units
                    SET pending_since = ?, expires_at = ?,
                        episode_count = episode_count + 1
                    WHERE requirement_unit_id = ?
                    """,
                    (now_text, expires_text, unit_id),
                )
                self._event(
                    connection,
                    emergency_id,
                    unit_id,
                    "PENDING_STARTED",
                    reason="No eligible resource could be requested.",
                    event_time=now_text,
                )

            self._recompute_statuses(connection, emergency_id)
            self._assert_invariants(connection, emergency_id)
            connection.commit()
            return True
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    @_synchronized
    def run_coordinator_pass(
        self, *, now: datetime | None = None
    ) -> list[dict]:
        """Evaluate pending units once and create at most one request per unit."""
        self._rebuild_heaps()
        now = now or _utc_now()
        now_text = _stamp(now)
        created_requests: list[dict] = []

        for resource_type in RESOURCE_TYPES:
            heap = self._heaps[resource_type]
            while heap.size > 0:
                entry = heap.pop()
                if entry is None:
                    break

                connection = self._connect()
                try:
                    unit = connection.execute(
                        """
                        SELECT ru.status, ru.pending_since, ru.expires_at,
                               ru.episode_count, rg.emergency_id
                        FROM Requirement_Units ru
                        JOIN Requirement_Groups rg
                          ON rg.requirement_group_id = ru.requirement_group_id
                        WHERE ru.requirement_unit_id = ?
                        """,
                        (entry["requirement_unit_id"],),
                    ).fetchone()
                    if (
                        unit is None
                        or unit["status"] != "PENDING"
                        or unit["emergency_id"] != entry["emergency_id"]
                    ):
                        continue

                    ranked = self._rank_candidates(
                        connection,
                        entry["emergency_id"],
                        resource_type,
                        entry["requirement_unit_id"],
                        now_text,
                    )
                    self._capture_ml_feature_snapshot(
                        connection,
                        entry["requirement_unit_id"],
                        entry["emergency_id"],
                        resource_type,
                        now,
                        ranked,
                    )
                    connection.commit()
                finally:
                    connection.close()

                request = self._reserve_candidate(
                    entry["requirement_unit_id"],
                    entry["emergency_id"],
                    resource_type,
                    ranked,
                    now,
                )
                if request is not None:
                    created_requests.append(request)
                    continue

                # No suitable candidate this pass. Start a bounded pending
                # episode only when one is not already active.
                if unit["pending_since"] is None:
                    self._start_pending_episode(
                        entry["requirement_unit_id"],
                        entry["emergency_id"],
                        now,
                    )
                elif unit["expires_at"] and unit["expires_at"] <= now_text:
                    self._expire_pending_unit(
                        entry["requirement_unit_id"],
                        entry["emergency_id"],
                        now,
                    )

        return created_requests

    def _expire_pending_unit(
        self,
        unit_id: str,
        emergency_id: str,
        now: datetime,
    ) -> bool:
        """Expire an episode only after a fresh candidate evaluation found none."""
        now_text = _stamp(now)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            unit = connection.execute(
                """
                SELECT status, pending_since, expires_at, episode_count
                FROM Requirement_Units
                WHERE requirement_unit_id = ?
                """,
                (unit_id,),
            ).fetchone()
            if (
                unit is None
                or unit["status"] != "PENDING"
                or unit["pending_since"] is None
                or unit["expires_at"] is None
                or unit["expires_at"] > now_text
            ):
                connection.rollback()
                return False

            connection.execute(
                """
                UPDATE Requirement_Units
                SET pending_since = NULL, expires_at = NULL,
                    status = CASE WHEN episode_count >= ?
                                  THEN 'UNFULFILLED' ELSE 'PENDING' END
                WHERE requirement_unit_id = ?
                """,
                (self.max_pending_episodes, unit_id),
            )
            if unit["episode_count"] >= self.max_pending_episodes:
                self._event(
                    connection,
                    emergency_id,
                    unit_id,
                    "UNFULFILLED",
                    reason="Pending episode expired; maximum episodes reached.",
                    event_time=now_text,
                )
            else:
                # A later pass may start the next bounded episode.
                self._event(
                    connection,
                    emergency_id,
                    unit_id,
                    "NO_SUITABLE_RESOURCE",
                    reason="Pending episode expired without an eligible resource.",
                    event_time=now_text,
                )

            self._recompute_statuses(connection, emergency_id)
            self._assert_invariants(connection, emergency_id)
            connection.commit()
            return True
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()
    def _load_allocation(self, connection, allocation_id: str):
        return connection.execute(
            """
            SELECT a.allocation_id, a.emergency_id, a.requirement_unit_id,
                   a.resource_id, a.response_status, a.status,
                   a.deadline_at, ru.status AS unit_status,
                   ru.requirement_group_id, rg.emergency_id AS unit_emergency_id,
                   r.status AS resource_status, r.organization_id,
                   o.status AS organization_status
            FROM Allocations a
            JOIN Requirement_Units ru
              ON ru.requirement_unit_id = a.requirement_unit_id
            JOIN Requirement_Groups rg
              ON rg.requirement_group_id = ru.requirement_group_id
            JOIN Resources r ON r.resource_id = a.resource_id
            JOIN Organizations o ON o.organization_id = r.organization_id
            WHERE a.allocation_id = ?
            """,
            (allocation_id,),
        ).fetchone()

    def _finish_transition(self, connection, emergency_id: str) -> None:
        self._recompute_statuses(connection, emergency_id)
        self._assert_invariants(connection, emergency_id)

    @_synchronized
    def organization_response(
        self,
        allocation_id: str,
        organization_id: str,
        *,
        accept: bool,
        reason: str | None = None,
        now: datetime | None = None,
    ) -> dict:
        """Accept or reject an organization's own outstanding request."""
        if not allocation_id or not organization_id:
            raise ValueError("allocation_id and organization_id are required.")
        now = now or _utc_now()
        now_text = _stamp(now)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            item = self._load_allocation(connection, allocation_id)
            if item is None or item["organization_id"] != organization_id:
                connection.rollback()
                return {"ok": False, "code": "ALLOCATION_NOT_FOUND"}
            if (
                item["status"] == "CLOSED"
                and item["response_status"] == "TIMEOUT"
            ):
                connection.rollback()
                return {"ok": False, "code": "ALLOCATION_EXPIRED"}

            if (
                item["status"] != "REQUESTED"
                or item["response_status"] != "PENDING"
                or item["unit_status"] != "REQUESTED"
                or item["resource_status"] != "REQUESTED"
            ):
                connection.rollback()
                return {"ok": False, "code": "ALLOCATION_NOT_PENDING"}

            if item["deadline_at"] <= now_text:
                connection.execute(
                    """
                    UPDATE Allocations
                    SET status = 'CLOSED', response_status = 'TIMEOUT',
                        response_at = ?
                    WHERE allocation_id = ?
                    """,
                    (now_text, allocation_id),
                )
                connection.execute(
                    "UPDATE Resources SET status = 'AVAILABLE', last_updated = ? "
                    "WHERE resource_id = ? AND status = 'REQUESTED'",
                    (now_text, item["resource_id"]),
                )
                connection.execute(
                    "UPDATE Requirement_Units SET status = 'PENDING' "
                    "WHERE requirement_unit_id = ? AND status = 'REQUESTED'",
                    (item["requirement_unit_id"],),
                )
                self._event(
                    connection, item["emergency_id"], item["requirement_unit_id"],
                    "TIMEOUT", resource_id=item["resource_id"],
                    reason="Organization response deadline elapsed.",
                    event_time=now_text,
                )
                self._finish_transition(connection, item["emergency_id"])
                connection.commit()
                self.run_coordinator_pass(now=now)
                return {"ok": False, "code": "ALLOCATION_EXPIRED"}

            if accept:
                connection.execute(
                    """
                    UPDATE Allocations
                    SET status = 'DISPATCHED', response_status = 'ACCEPTED',
                        response_at = ?, dispatched_at = ?
                    WHERE allocation_id = ?
                    """,
                    (now_text, now_text, allocation_id),
                )
                connection.execute(
                    "UPDATE Resources SET status = 'DISPATCHED', last_updated = ? "
                    "WHERE resource_id = ? AND status = 'REQUESTED'",
                    (now_text, item["resource_id"]),
                )
                connection.execute(
                    """
                    UPDATE Requirement_Units
                    SET status = 'DISPATCHED', pending_since = NULL, expires_at = NULL
                    WHERE requirement_unit_id = ? AND status = 'REQUESTED'
                    """,
                    (item["requirement_unit_id"],),
                )
                event_type = "ACCEPTED"
                event_reason = None
            else:
                connection.execute(
                    """
                    UPDATE Allocations
                    SET status = 'CLOSED', response_status = 'REJECTED',
                        response_at = ?, rejection_reason = ?
                    WHERE allocation_id = ?
                    """,
                    (now_text, reason, allocation_id),
                )
                connection.execute(
                    "UPDATE Resources SET status = 'AVAILABLE', last_updated = ? "
                    "WHERE resource_id = ? AND status = 'REQUESTED'",
                    (now_text, item["resource_id"]),
                )
                connection.execute(
                    "UPDATE Requirement_Units SET status = 'PENDING' "
                    "WHERE requirement_unit_id = ? AND status = 'REQUESTED'",
                    (item["requirement_unit_id"],),
                )
                event_type = "REJECTED"
                event_reason = reason

            self._event(
                connection, item["emergency_id"], item["requirement_unit_id"],
                event_type, resource_id=item["resource_id"],
                reason=event_reason, event_time=now_text,
            )
            self._finish_transition(connection, item["emergency_id"])
            connection.commit()
            if event_type == "REJECTED":
                self.run_coordinator_pass(now=now)
            return {"ok": True, "code": event_type, "allocation_id": allocation_id}
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    @_synchronized
    def complete_allocation(
        self, allocation_id: str, organization_id: str, *,
        now: datetime | None = None,
    ) -> dict:
        """Mark an accepted dispatch complete and release its resource."""
        now = now or _utc_now()
        now_text = _stamp(now)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            item = self._load_allocation(connection, allocation_id)
            if item is None or item["organization_id"] != organization_id:
                connection.rollback()
                return {"ok": False, "code": "ALLOCATION_NOT_FOUND"}
            if item["status"] != "DISPATCHED" or item["response_status"] != "ACCEPTED":
                connection.rollback()
                return {"ok": False, "code": "ALLOCATION_NOT_DISPATCHED"}

            connection.execute(
                """
                UPDATE Allocations
                SET status = 'COMPLETED', completed_at = ?, returned_at = ?
                WHERE allocation_id = ?
                """,
                (now_text, now_text, allocation_id),
            )
            connection.execute(
                """
                UPDATE Requirement_Units SET status = 'FULFILLED'
                WHERE requirement_unit_id = ? AND status = 'DISPATCHED'
                """,
                (item["requirement_unit_id"],),
            )
            connection.execute(
                """
                UPDATE Resources SET status = ?, last_updated = ?
                WHERE resource_id = ? AND status = 'DISPATCHED'
                """,
                (
                    "AVAILABLE" if item["organization_status"] == "ACTIVE" else "INACTIVE",
                    now_text, item["resource_id"],
                ),
            )
            self._event(
                connection, item["emergency_id"], item["requirement_unit_id"],
                "COMPLETED", resource_id=item["resource_id"], event_time=now_text,
            )
            self._finish_transition(connection, item["emergency_id"])
            connection.commit()
            return {"ok": True, "code": "COMPLETED", "allocation_id": allocation_id}
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    @_synchronized
    def fail_allocation(
        self, allocation_id: str, organization_id: str, reason: str, *,
        now: datetime | None = None,
    ) -> dict:
        """Return a failed dispatch to the pending allocation workflow."""
        if not reason or not reason.strip():
            raise ValueError("A failure reason is required.")
        now = now or _utc_now()
        now_text = _stamp(now)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            item = self._load_allocation(connection, allocation_id)
            if item is None or item["organization_id"] != organization_id:
                connection.rollback()
                return {"ok": False, "code": "ALLOCATION_NOT_FOUND"}
            if item["status"] != "DISPATCHED" or item["response_status"] != "ACCEPTED":
                connection.rollback()
                return {"ok": False, "code": "ALLOCATION_NOT_DISPATCHED"}

            connection.execute(
                """
                UPDATE Allocations SET status = 'FAILED', returned_at = ?
                WHERE allocation_id = ?
                """,
                (now_text, allocation_id),
            )
            connection.execute(
                """
                UPDATE Resources SET status = 'UNAVAILABLE', last_updated = ?
                WHERE resource_id = ? AND status = 'DISPATCHED'
                """,
                (now_text, item["resource_id"]),
            )
            connection.execute(
                """
                UPDATE Requirement_Units
                SET status = 'PENDING', pending_since = NULL, expires_at = NULL
                WHERE requirement_unit_id = ? AND status = 'DISPATCHED'
                """,
                (item["requirement_unit_id"],),
            )
            self._event(
                connection, item["emergency_id"], item["requirement_unit_id"],
                "FAILED", resource_id=item["resource_id"],
                reason=reason.strip(), event_time=now_text,
            )
            self._finish_transition(connection, item["emergency_id"])
            connection.commit()
            self.run_coordinator_pass(now=now)
            return {"ok": True, "code": "FAILED", "allocation_id": allocation_id}
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    @_synchronized
    def process_allocation_timeouts(self, *, now: datetime | None = None) -> int:
        """Close all expired requests; pending timestamps are deliberately preserved."""
        now = now or _utc_now()
        now_text = _stamp(now)
        connection = self._connect()
        changed = 0
        try:
            connection.execute("BEGIN IMMEDIATE")
            expired = connection.execute(
                """
                SELECT a.allocation_id, a.emergency_id, a.requirement_unit_id,
                       a.resource_id
                FROM Allocations a
                JOIN Requirement_Units ru
                  ON ru.requirement_unit_id = a.requirement_unit_id
                WHERE a.status = 'REQUESTED'
                  AND a.response_status = 'PENDING'
                  AND a.deadline_at <= ?
                  AND ru.status = 'REQUESTED'
                ORDER BY a.deadline_at, a.allocation_id
                """,
                (now_text,),
            ).fetchall()
            for item in expired:
                connection.execute(
                    """
                    UPDATE Allocations
                    SET status = 'CLOSED', response_status = 'TIMEOUT', response_at = ?
                    WHERE allocation_id = ? AND status = 'REQUESTED'
                      AND response_status = 'PENDING'
                    """,
                    (now_text, item["allocation_id"]),
                )
                if connection.execute("SELECT changes()").fetchone()[0] != 1:
                    continue
                connection.execute(
                    "UPDATE Resources SET status = 'AVAILABLE', last_updated = ? "
                    "WHERE resource_id = ? AND status = 'REQUESTED'",
                    (now_text, item["resource_id"]),
                )
                connection.execute(
                    "UPDATE Requirement_Units SET status = 'PENDING' "
                    "WHERE requirement_unit_id = ? AND status = 'REQUESTED'",
                    (item["requirement_unit_id"],),
                )
                self._event(
                    connection, item["emergency_id"], item["requirement_unit_id"],
                    "TIMEOUT", resource_id=item["resource_id"],
                    reason="Organization response deadline elapsed.",
                    event_time=now_text,
                )
                self._finish_transition(connection, item["emergency_id"])
                changed += 1
            connection.commit()
            if changed:
                self.run_coordinator_pass(now=now)
            return changed
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def assert_invariants(self) -> None:
        """Validate cross-table allocation invariants across the whole database."""
        connection = self._connect()
        try:
            rows = connection.execute(
                "SELECT emergency_id FROM Emergencies"
            ).fetchall()
            for row in rows:
                self._assert_invariants(connection, row["emergency_id"])
            duplicate_active = connection.execute(
                """
                SELECT resource_id FROM Allocations
                WHERE status IN ('REQUESTED', 'DISPATCHED')
                GROUP BY resource_id HAVING COUNT(*) > 1
                """
            ).fetchall()
            if duplicate_active:
                raise RuntimeError("Invariant violation: resource has multiple active allocations.")
        finally:
            connection.close()

    @_synchronized
    def sweep_once(self, *, now: datetime | None = None) -> dict:
        """Run timeout processing before reevaluating pending units."""
        timed_out = self.process_allocation_timeouts(now=now)
        requests = self.run_coordinator_pass(now=now)
        self.assert_invariants()
        return {"timed_out": timed_out, "requests_created": requests}
