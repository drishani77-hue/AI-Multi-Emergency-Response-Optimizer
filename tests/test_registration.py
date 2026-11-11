
import sqlite3

import pytest

from backend.app import create_app
from backend.db import SCHEMA_PATH
from backend.security import hash_password, verify_password


FRONTEND_ORIGIN = "http://localhost:5173"


@pytest.fixture
def registration_client(tmp_path, monkeypatch):
    db_path = tmp_path / "registration_test.db"

    connection = sqlite3.connect(db_path)
    connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    connection.close()

    monkeypatch.setenv("RESQTECH_ADMIN_ID", "admin_test")
    monkeypatch.setenv("RESQTECH_ADMIN_EMAIL", "admin@example.org")
    monkeypatch.setenv(
        "RESQTECH_ADMIN_PASSWORD_HASH",
        hash_password("AdminTestPassword123!"),
    )
    monkeypatch.setenv("RESQTECH_ADMIN_CAN_OVERRIDE_SEVERITY", "false")

    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": db_path,
        "FRONTEND_ORIGIN": FRONTEND_ORIGIN,
        "SESSION_COOKIE_SECURE": False,
    })

    return app.test_client(), db_path


def valid_payload(**overrides):
    payload = {
        "name": "  Example Medical Centre  ",
        "organization_type": "HOSPITAL_MEDICAL",
        "ownership": "PRIVATE",
        "phone": "  9876543210  ",
        "email": "  org@example.org  ",
        "password": "OrganizationPass123!",
    }
    payload.update(overrides)
    return payload


def register(client, payload):
    return client.post(
        "/organization",
        json=payload,
        headers={"Origin": FRONTEND_ORIGIN},
    )


def test_registration_creates_active_organization_without_login(
    registration_client,
):
    client, db_path = registration_client

    response = register(client, valid_payload())

    assert response.status_code == 201

    body = response.get_json()

    assert body["name"] == "Example Medical Centre"
    assert body["status"] == "ACTIVE"
    assert body["organization_id"].startswith("org_")
    assert set(body) == {"organization_id", "name", "status"}

    assert "Set-Cookie" not in response.headers
    assert client.get_cookie("resqtech_session") is None
    assert client.get_cookie("resqtech_csrf") is None

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    organization = connection.execute(
        """
        SELECT *
        FROM Organizations
        WHERE organization_id = ?
        """,
        (body["organization_id"],),
    ).fetchone()

    connection.close()

    assert organization is not None
    assert organization["name"] == "Example Medical Centre"
    assert organization["phone"] == "9876543210"
    assert organization["email"] == "org@example.org"
    assert organization["status"] == "ACTIVE"
    assert organization["password_hash"] != "OrganizationPass123!"
    assert verify_password(
        "OrganizationPass123!",
        organization["password_hash"],
    )


def test_registration_allows_missing_optional_phone(registration_client):
    client, db_path = registration_client

    payload = valid_payload()
    del payload["phone"]

    response = register(client, payload)

    assert response.status_code == 201

    connection = sqlite3.connect(db_path)
    phone = connection.execute(
        "SELECT phone FROM Organizations WHERE email = ?",
        ("org@example.org",),
    ).fetchone()[0]
    connection.close()

    assert phone is None


def test_registration_rejects_duplicate_normalized_email(
    registration_client,
):
    client, db_path = registration_client

    first = register(client, valid_payload())
    assert first.status_code == 201

    second = register(
        client,
        valid_payload(
            email="ORG@EXAMPLE.ORG",
            name="Another Medical Centre",
        ),
    )

    assert second.status_code == 409
    assert second.get_json()["error"] == "EMAIL_ALREADY_REGISTERED"

    connection = sqlite3.connect(db_path)
    count = connection.execute(
        "SELECT COUNT(*) FROM Organizations"
    ).fetchone()[0]
    connection.close()

    assert count == 1


def test_registration_rejects_configured_admin_email(registration_client):
    client, _ = registration_client

    response = register(
        client,
        valid_payload(email="ADMIN@example.org"),
    )

    assert response.status_code == 409
    assert response.get_json()["error"] == "EMAIL_ALREADY_REGISTERED"


@pytest.mark.parametrize(
    "overrides, expected_error",
    [
        ({"name": "   "}, "INVALID_REQUEST"),
        ({"organization_type": "UNKNOWN"}, "INVALID_ORGANIZATION_TYPE"),
        ({"ownership": "UNKNOWN"}, "INVALID_OWNERSHIP"),
        ({"email": "not-an-email"}, "INVALID_EMAIL"),
        ({"email": "tést@example.org"}, "INVALID_EMAIL"),
        ({"password": "short"}, "INVALID_PASSWORD"),
        ({"password": "x" * 129}, "INVALID_PASSWORD"),
        ({"extra_field": "not allowed"}, "INVALID_REQUEST"),
        ({"organization_id": "org_attacker"}, "INVALID_REQUEST"),
        ({"password_hash": "attacker-controlled"}, "INVALID_REQUEST"),
        ({"status": "ACTIVE"}, "INVALID_REQUEST"),
    ],
)
def test_registration_rejects_invalid_or_unknown_fields(
    registration_client,
    overrides,
    expected_error,
):
    client, _ = registration_client

    response = register(client, valid_payload(**overrides))

    assert response.status_code == 400
    assert response.get_json()["error"] == expected_error


def test_registration_rejects_non_json_body(registration_client):
    client, _ = registration_client

    response = client.post(
        "/organization",
        data="not json",
        content_type="text/plain",
        headers={"Origin": FRONTEND_ORIGIN},
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "INVALID_REQUEST"


def test_registration_requires_permitted_origin(registration_client):
    client, _ = registration_client

    response = client.post(
        "/organization",
        json=valid_payload(),
        headers={"Origin": "https://untrusted.example"},
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "INVALID_ORIGIN"
