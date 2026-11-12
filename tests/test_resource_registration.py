
import sqlite3
from datetime import datetime

import pytest

from backend.app import create_app
from backend.security import hash_password


FRONTEND_ORIGIN = "http://localhost:5173"
ADMIN_PASSWORD = "AdminTestPassword123!"
ORG_PASSWORD = "OrgTestPassword123!"


@pytest.fixture
def db_path(tmp_path):
    from backend.db import SCHEMA_PATH

    path = tmp_path / "test_resource_registration.db"

    connection = sqlite3.connect(path)

    with open(SCHEMA_PATH, "r", encoding="utf-8") as schema_file:
        connection.executescript(schema_file.read())

    connection.execute(
        """
        INSERT INTO Organizations (
            organization_id,
            name,
            organization_type,
            ownership,
            phone,
            email,
            password_hash,
            status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "ORG001",
            "Test Hospital",
            "HOSPITAL_MEDICAL",
            "GOVERNMENT",
            "9876543210",
            "hospital@example.com",
            hash_password(ORG_PASSWORD),
            "ACTIVE",
        ),
    )

    connection.execute(
        """
        INSERT INTO Locations (
            location_id,
            district,
            locality,
            specific_location
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            "LOC001",
            "Dehradun",
            "Clement Town",
            "Graphic Era University Gate 1",
        ),
    )

    connection.commit()
    connection.close()

    return path


@pytest.fixture
def admin_environment(monkeypatch):
    monkeypatch.setenv("RESQTECH_ADMIN_ID", "ADMIN001")
    monkeypatch.setenv("RESQTECH_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv(
        "RESQTECH_ADMIN_PASSWORD_HASH",
        hash_password(ADMIN_PASSWORD),
    )
    monkeypatch.delenv(
        "RESQTECH_ADMIN_CAN_OVERRIDE_SEVERITY",
        raising=False,
    )


@pytest.fixture
def app(db_path, admin_environment):
    return create_app({
        "TESTING": True,
        "DATABASE_PATH": db_path,
        "FRONTEND_ORIGIN": FRONTEND_ORIGIN,
        "SESSION_COOKIE_SECURE": False,
    })


@pytest.fixture
def client(app):
    return app.test_client()


def login_organization(client):
    response = client.post(
        "/auth/login",
        json={
            "email": "hospital@example.com",
            "password": ORG_PASSWORD,
        },
        headers={"Origin": FRONTEND_ORIGIN},
    )

    assert response.status_code == 200

    csrf_cookie = client.get_cookie("resqtech_csrf")
    assert csrf_cookie is not None

    return {
        "Origin": FRONTEND_ORIGIN,
        "X-CSRF-Token": csrf_cookie.value,
    }


def login_admin(client):
    response = client.post(
        "/auth/login",
        json={
            "email": "admin@example.com",
            "password": ADMIN_PASSWORD,
        },
        headers={"Origin": FRONTEND_ORIGIN},
    )

    assert response.status_code == 200


def valid_resource_payload():
    return {
        "resource_type": "AMBULANCE",
        "base_location_id": "LOC001",
        "status": "AVAILABLE",
    }


@pytest.mark.parametrize(
    "resource_type",
    [
        "AMBULANCE",
        "FIRE_VEHICLE",
        "POLICE_UNIT",
        "RESCUE_VEHICLE",
    ],
)
@pytest.mark.parametrize(
    "status",
    ["AVAILABLE", "UNAVAILABLE"],
)
def test_resource_registration_success(
    client,
    db_path,
    resource_type,
    status,
):
    headers = login_organization(client)

    payload = valid_resource_payload()
    payload["resource_type"] = resource_type
    payload["status"] = status

    response = client.post(
        "/resource",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 201

    result = response.get_json()

    assert result["resource_id"].startswith("res_")
    assert len(result["resource_id"]) == 20
    assert result["resource_type"] == resource_type
    assert result["base_location_id"] == "LOC001"
    assert result["last_reported_location_id"] == "LOC001"
    assert result["status"] == status

    datetime.strptime(
        result["last_updated"],
        "%Y-%m-%dT%H:%M:%SZ",
    )

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    resource = connection.execute(
        """
        SELECT *
        FROM Resources
        WHERE resource_id = ?
        """,
        (result["resource_id"],),
    ).fetchone()

    connection.close()

    assert resource is not None
    assert resource["organization_id"] == "ORG001"
    assert resource["resource_type"] == resource_type
    assert resource["base_location_id"] == "LOC001"
    assert resource["last_reported_location_id"] == "LOC001"
    assert resource["status"] == status
    assert resource["last_updated"] == result["last_updated"]


def test_resource_registration_requires_authentication(client):
    response = client.post(
        "/resource",
        json=valid_resource_payload(),
        headers={"Origin": FRONTEND_ORIGIN},
    )

    assert response.status_code == 401


def test_admin_cannot_register_resources(client):
    login_admin(client)

    csrf_cookie = client.get_cookie("resqtech_csrf")
    assert csrf_cookie is not None

    response = client.post(
        "/resource",
        json=valid_resource_payload(),
        headers={
            "Origin": FRONTEND_ORIGIN,
            "X-CSRF-Token": csrf_cookie.value,
        },
    )

    assert response.status_code == 403


def test_resource_registration_rejects_missing_json(client):
    headers = login_organization(client)

    response = client.post(
        "/resource",
        headers=headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "INVALID_REQUEST"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "resource_type": "AMBULANCE",
            "base_location_id": "LOC001",
        },
        {
            "resource_type": "AMBULANCE",
            "base_location_id": "LOC001",
            "status": "AVAILABLE",
            "organization_id": "ORG001",
        },
    ],
)
def test_resource_registration_requires_exact_fields(
    client,
    payload,
):
    headers = login_organization(client)

    response = client.post(
        "/resource",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "INVALID_REQUEST"


def test_resource_registration_rejects_non_object_json(client):
    headers = login_organization(client)

    response = client.post(
        "/resource",
        json=["AMBULANCE", "LOC001", "AVAILABLE"],
        headers=headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "INVALID_REQUEST"


@pytest.mark.parametrize(
    "resource_type",
    [
        "INVALID",
        "ambulance",
        "",
        None,
    ],
)
def test_resource_registration_rejects_invalid_resource_type(
    client,
    resource_type,
):
    headers = login_organization(client)

    payload = valid_resource_payload()
    payload["resource_type"] = resource_type

    response = client.post(
        "/resource",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "INVALID_RESOURCE_TYPE"


@pytest.mark.parametrize(
    "base_location_id",
    [
        "",
        "   ",
        None,
    ],
)
def test_resource_registration_rejects_invalid_base_location(
    client,
    base_location_id,
):
    headers = login_organization(client)

    payload = valid_resource_payload()
    payload["base_location_id"] = base_location_id

    response = client.post(
        "/resource",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "INVALID_BASE_LOCATION"


@pytest.mark.parametrize(
    "status",
    [
        "REQUESTED",
        "DISPATCHED",
        "INACTIVE",
        "INVALID",
        "",
        None,
    ],
)
def test_resource_registration_rejects_invalid_initial_status(
    client,
    status,
):
    headers = login_organization(client)

    payload = valid_resource_payload()
    payload["status"] = status

    response = client.post(
        "/resource",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "INVALID_RESOURCE_STATUS"


def test_resource_registration_rejects_unknown_location(client):
    headers = login_organization(client)

    payload = valid_resource_payload()
    payload["base_location_id"] = "UNKNOWN_LOCATION"

    response = client.post(
        "/resource",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 404
    assert response.get_json()["error"] == "LOCATION_NOT_FOUND"


def test_resource_registration_rejects_inactive_organization(
    client,
    db_path,
):
    headers = login_organization(client)

    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        UPDATE Organizations
        SET status = 'INACTIVE'
        WHERE organization_id = ?
        """,
        ("ORG001",),
    )
    connection.commit()
    connection.close()

    response = client.post(
        "/resource",
        json=valid_resource_payload(),
        headers=headers,
    )

    # Inactive organizations have their sessions invalidated
    # by get_active_session() before the route is reached.
    assert response.status_code == 401
    assert response.get_json()["error"] == "UNAUTHENTICATED"

    connection = sqlite3.connect(db_path)

    resource_count = connection.execute(
        "SELECT COUNT(*) FROM Resources"
    ).fetchone()[0]

    connection.close()

    assert resource_count == 0


def test_resource_registration_does_not_trust_client_organization_id(
    client,
    db_path,
):
    headers = login_organization(client)

    payload = valid_resource_payload()
    payload["organization_id"] = "ANOTHER_ORG"

    response = client.post(
        "/resource",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 400

    connection = sqlite3.connect(db_path)

    resource_count = connection.execute(
        "SELECT COUNT(*) FROM Resources"
    ).fetchone()[0]

    connection.close()

    assert resource_count == 0

def test_emergency_report_unresolved_location_idempotent_retry(
    client,
):
    payload = {
        "emergency_type": "MEDICAL_EMERGENCY",
        "location_id": "LOC001",
        "location_text": (
            "Dehradun, Clement Town, Graphic Era University Gate 1"
        ),
        "assessment_answers": {},
        "description": (
            "A person needs urgent medical assistance near "
            "the university gate."
        ),
        "reporter_name": "Test Reporter",
        "reporter_phone": "9876543210",
        "reporter_type": "CITIZEN",
        "idempotency_key": "12345678-1234-4234-8234-123456789abc",
    }

    first_response = client.post(
    "/emergency",
    json=payload,
    headers={"Origin": FRONTEND_ORIGIN},
    )

    assert first_response.status_code == 201

    first_data = first_response.get_json()

    assert first_data["status"] == "PENDING"
    assert first_data["location_resolved"] is False
    assert first_data["emergency_id"]

    retry_response = client.post(
    "/emergency",
    json=payload,
    headers={"Origin": FRONTEND_ORIGIN},
    )

    assert retry_response.status_code == 200

    retry_data = retry_response.get_json()

    assert retry_data["emergency_id"] == first_data["emergency_id"]
    assert retry_data["reported_at"] == first_data["reported_at"]

    conflicting_payload = {
        **payload,
        "description": (
            "A different emergency report with changed details "
            "near the university gate."
        ),
    }

    conflict_response = client.post(
        "/emergency",
        json=conflicting_payload,
        headers={"Origin": FRONTEND_ORIGIN},
    )

    assert conflict_response.status_code == 409
    assert (
        conflict_response.get_json()["error"]
        == "IDEMPOTENCY_KEY_CONFLICT"
    )

def test_new_emergency_requirement_units_have_no_pending_episode(
    client,
    db_path,
):
    payload = {
        "emergency_type": "FIRE",
        "location_id": "LOC001",
        "location_text": (
            "Dehradun, Clement Town, Graphic Era University Gate 1"
        ),
        "assessment_answers": {},
        "description": (
            "A fire has been reported near the university gate. "
            "Emergency assistance is required."
        ),
        "reporter_name": "Test Reporter",
        "reporter_phone": "9876543210",
        "reporter_type": "CITIZEN",
        "idempotency_key": "22345678-1234-4234-8234-123456789abc",
    }

    response = client.post(
        "/emergency",
        json=payload,
        headers={"Origin": FRONTEND_ORIGIN},
    )

    assert response.status_code == 201

    emergency_id = response.get_json()["emergency_id"]

    connection = sqlite3.connect(db_path)

    try:
        rows = connection.execute(
            """
            SELECT pending_since, expires_at, episode_count
            FROM Requirement_Units
            WHERE requirement_group_id IN (
                SELECT requirement_group_id
                FROM Requirement_Groups
                WHERE emergency_id = ?
            )
            """,
            (emergency_id,),
        ).fetchall()
    finally:
        connection.close()

    assert len(rows) >= 2

    assert all(
        pending_since is None
        and expires_at is None
        and episode_count == 0
        for pending_since, expires_at, episode_count in rows
    )
