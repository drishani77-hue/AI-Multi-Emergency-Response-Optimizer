
import sqlite3

import pytest

from backend.app import create_app
from backend.security import hash_password
from backend.sessions import get_active_session


FRONTEND_ORIGIN = "http://localhost:5173"
ADMIN_PASSWORD = "AdminTestPassword123!"
ORG_PASSWORD = "HospitalTestPassword123!"


@pytest.fixture
def db_path(tmp_path):
    """Create an isolated database using the actual project schema."""

    from backend.db import SCHEMA_PATH

    path = tmp_path / "test_resqtech.db"
    connection = sqlite3.connect(path)

    try:
        connection.executescript(
            SCHEMA_PATH.read_text(encoding="utf-8")
        )

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

        connection.commit()

    finally:
        connection.close()

    return path


@pytest.fixture
def admin_environment(monkeypatch):
    """Provide valid isolated Admin configuration."""

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
    """Create a Flask application using the temporary database."""

    return create_app({
        "TESTING": True,
        "DATABASE_PATH": db_path,
        "FRONTEND_ORIGIN": FRONTEND_ORIGIN,
        "SESSION_COOKIE_SECURE": False,
    })


@pytest.fixture
def client(app):
    return app.test_client()


def login_headers():
    return {"Origin": FRONTEND_ORIGIN}


def test_organization_login_success(client):
    response = client.post(
        "/auth/login",
        json={
            "email": " HOSPITAL@EXAMPLE.COM ",
            "password": ORG_PASSWORD,
        },
        headers=login_headers(),
    )

    assert response.status_code == 200

    data = response.get_json()

    assert data["role"] == "ORGANIZATION"
    assert data["organization"]["organization_id"] == "ORG001"
    assert data["organization"]["name"] == "Test Hospital"

    assert "session_token" not in data
    assert "csrf_token" not in data
    assert "password_hash" not in data

    session_cookie = client.get_cookie("resqtech_session")
    csrf_cookie = client.get_cookie("resqtech_csrf")

    assert session_cookie is not None
    assert csrf_cookie is not None

    assert session_cookie.value
    assert csrf_cookie.value

    assert session_cookie.http_only is True
    assert csrf_cookie.http_only is False

    assert session_cookie.same_site == "Lax"
    assert csrf_cookie.same_site == "Lax"


def test_admin_login_success(client):
    response = client.post(
        "/auth/login",
        json={
            "email": "admin@example.com",
            "password": ADMIN_PASSWORD,
        },
        headers=login_headers(),
    )

    assert response.status_code == 200

    data = response.get_json()

    assert data["role"] == "ADMIN"
    assert data["admin"]["admin_id"] == "ADMIN001"

    assert "password_hash" not in data
    assert "session_token" not in data
    assert "csrf_token" not in data

    assert client.get_cookie("resqtech_session") is not None
    assert client.get_cookie("resqtech_csrf") is not None


def test_login_rejects_wrong_password(client):
    response = client.post(
        "/auth/login",
        json={
            "email": "hospital@example.com",
            "password": "WrongPassword123!",
        },
        headers=login_headers(),
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "INVALID_CREDENTIALS"

    assert client.get_cookie("resqtech_session") is None
    assert client.get_cookie("resqtech_csrf") is None


def test_login_rejects_unknown_email(client):
    response = client.post(
        "/auth/login",
        json={
            "email": "unknown@example.com",
            "password": ORG_PASSWORD,
        },
        headers=login_headers(),
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "INVALID_CREDENTIALS"


def test_login_rejects_inactive_organization(
    client,
    db_path,
):
    connection = sqlite3.connect(db_path)

    try:
        connection.execute(
            """
            UPDATE Organizations
            SET status = 'INACTIVE'
            WHERE organization_id = 'ORG001'
            """
        )
        connection.commit()
    finally:
        connection.close()

    response = client.post(
        "/auth/login",
        json={
            "email": "hospital@example.com",
            "password": ORG_PASSWORD,
        },
        headers=login_headers(),
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "INVALID_CREDENTIALS"


def test_login_rejects_invalid_json(client):
    response = client.post(
        "/auth/login",
        data="not-json",
        content_type="application/json",
        headers=login_headers(),
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "INVALID_REQUEST"


def test_login_rejects_missing_fields(client):
    response = client.post(
        "/auth/login",
        json={"email": "hospital@example.com"},
        headers=login_headers(),
    )

    assert response.status_code == 400
    assert response.get_json()["error"] == "INVALID_REQUEST"


def test_login_rejects_untrusted_origin(client):
    response = client.post(
        "/auth/login",
        json={
            "email": "admin@example.com",
            "password": ADMIN_PASSWORD,
        },
        headers={"Origin": "https://untrusted.example"},
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "INVALID_ORIGIN"


def test_login_rate_limit(client):
    payload = {
        "email": "unknown@example.com",
        "password": "WrongPassword123!",
    }

    for _ in range(5):
        response = client.post(
            "/auth/login",
            json=payload,
            headers={
                **login_headers(),
                "X-Forwarded-For": "192.0.2.50",
            },
            environ_base={"REMOTE_ADDR": "192.0.2.50"},
        )

        assert response.status_code == 401

    response = client.post(
        "/auth/login",
        json=payload,
        headers=login_headers(),
        environ_base={"REMOTE_ADDR": "192.0.2.50"},
    )

    assert response.status_code == 429
    assert response.get_json()["error"] == "RATE_LIMITED"


def test_logout_requires_authentication(client):
    response = client.post(
        "/auth/logout",
        headers=login_headers(),
    )

    assert response.status_code == 401
    assert response.get_json()["error"] == "UNAUTHENTICATED"


def test_logout_requires_valid_csrf_token(
    client,
    db_path,
):
    login_response = client.post(
        "/auth/login",
        json={
            "email": "hospital@example.com",
            "password": ORG_PASSWORD,
        },
        headers=login_headers(),
    )

    assert login_response.status_code == 200

    session_cookie = client.get_cookie("resqtech_session")

    response = client.post(
        "/auth/logout",
        headers={
            **login_headers(),
            "X-CSRF-Token": "invalid-token",
        },
    )

    assert response.status_code == 403
    assert response.get_json()["error"] == "INVALID_CSRF_TOKEN"

    session = get_active_session(
        session_cookie.value,
        db_path,
    )

    assert session is not None


def test_logout_successfully_revokes_session(
    client,
    db_path,
):
    login_response = client.post(
        "/auth/login",
        json={
            "email": "hospital@example.com",
            "password": ORG_PASSWORD,
        },
        headers=login_headers(),
    )

    assert login_response.status_code == 200

    session_cookie = client.get_cookie("resqtech_session")
    csrf_cookie = client.get_cookie("resqtech_csrf")

    response = client.post(
        "/auth/logout",
        headers={
            **login_headers(),
            "X-CSRF-Token": csrf_cookie.value,
        },
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True}

    assert client.get_cookie("resqtech_session") is None
    assert client.get_cookie("resqtech_csrf") is None

    session = get_active_session(
        session_cookie.value,
        db_path,
    )

    assert session is None


def test_login_returns_credentialed_cors_headers(client):
    response = client.post(
        "/auth/login",
        json={
            "email": "admin@example.com",
            "password": ADMIN_PASSWORD,
        },
        headers=login_headers(),
    )

    assert response.headers["Access-Control-Allow-Origin"] == (
        FRONTEND_ORIGIN
    )

    assert response.headers["Access-Control-Allow-Credentials"] == "true"


def test_startup_rejects_malformed_admin_hash(
    db_path,
    monkeypatch,
):
    monkeypatch.setenv("RESQTECH_ADMIN_ID", "ADMIN001")
    monkeypatch.setenv("RESQTECH_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv(
        "RESQTECH_ADMIN_PASSWORD_HASH",
        "not-a-valid-hash",
    )

    with pytest.raises(RuntimeError):
        create_app({
            "TESTING": True,
            "DATABASE_PATH": db_path,
            "FRONTEND_ORIGIN": FRONTEND_ORIGIN,
        })
