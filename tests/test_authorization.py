

import pytest

from flask import Flask, g, jsonify

import backend.auth as auth
from backend.app import SESSION_COOKIE


@pytest.fixture
def app():
    """Create a small Flask app for testing authorization decorators."""

    application = Flask(__name__)
    application.config["DATABASE_PATH"] = "test.db"

    @application.get("/organization")
    @auth.require_roles("ORGANIZATION")
    def organization_route():
        return jsonify({
            "message": "organization access granted",
            "principal": g.resqtech_principal,
        })

    @application.get("/admin")
    @auth.require_roles("ADMIN")
    def admin_route():
        return jsonify({
            "message": "admin access granted",
            "principal": g.resqtech_principal,
        })

    @application.get("/shared")
    @auth.require_roles("ORGANIZATION", "ADMIN")
    def shared_route():
        return jsonify({"message": "access granted"})

    @application.post("/organization/update")
    @auth.require_roles("ORGANIZATION")
    def update_route():
        return jsonify({"message": "update accepted"})

    return application


@pytest.fixture
def client(app):
    return app.test_client()


def set_active_session(monkeypatch, principal_type="ORGANIZATION"):
    """Mock a valid session returned by the session service."""

    session = {
        "principal_type": principal_type,
        "principal_id": (
            "org_001"
            if principal_type == "ORGANIZATION"
            else "admin_001"
        ),
        "organization_id": (
            "org_001"
            if principal_type == "ORGANIZATION"
            else None
        ),
    }

    monkeypatch.setattr(
        auth,
        "get_active_session",
        lambda token, db_path: session,
    )

    return session


def test_missing_session_returns_401(client):
    response = client.get("/organization")

    assert response.status_code == 401
    assert response.get_json()["error"] == "UNAUTHENTICATED"


def test_invalid_session_returns_401(client, monkeypatch):
    monkeypatch.setattr(
        auth,
        "get_active_session",
        lambda token, db_path: None,
    )

    client.set_cookie(SESSION_COOKIE, "invalid-token")

    response = client.get("/organization")

    assert response.status_code == 401
    assert response.get_json()["error"] == "UNAUTHENTICATED"


def test_organization_can_access_organization_route(
    client,
    monkeypatch,
):
    set_active_session(monkeypatch, "ORGANIZATION")
    client.set_cookie(SESSION_COOKIE, "valid-token")

    response = client.get("/organization")

    assert response.status_code == 200
    assert response.get_json()["principal"] == {
        "type": "ORGANIZATION",
        "id": "org_001",
        "organization_id": "org_001",
    }


def test_admin_cannot_access_organization_only_route(
    client,
    monkeypatch,
):
    set_active_session(monkeypatch, "ADMIN")
    client.set_cookie(SESSION_COOKIE, "valid-token")

    response = client.get("/organization")

    assert response.status_code == 403
    assert response.get_json()["error"] == "FORBIDDEN"


def test_organization_cannot_access_admin_only_route(
    client,
    monkeypatch,
):
    set_active_session(monkeypatch, "ORGANIZATION")
    client.set_cookie(SESSION_COOKIE, "valid-token")

    response = client.get("/admin")

    assert response.status_code == 403
    assert response.get_json()["error"] == "FORBIDDEN"


def test_admin_can_access_admin_only_route(
    client,
    monkeypatch,
):
    set_active_session(monkeypatch, "ADMIN")
    client.set_cookie(SESSION_COOKIE, "valid-token")

    response = client.get("/admin")

    assert response.status_code == 200
    assert response.get_json()["principal"]["type"] == "ADMIN"


@pytest.mark.parametrize("principal_type", ["ORGANIZATION", "ADMIN"])
def test_shared_route_accepts_both_roles(
    client,
    monkeypatch,
    principal_type,
):
    set_active_session(monkeypatch, principal_type)
    client.set_cookie(SESSION_COOKIE, "valid-token")

    response = client.get("/shared")

    assert response.status_code == 200


def test_state_changing_request_requires_csrf_token(
    client,
    monkeypatch,
):
    set_active_session(monkeypatch, "ORGANIZATION")
    client.set_cookie(SESSION_COOKIE, "valid-token")

    monkeypatch.setattr(
        auth,
        "verify_session_csrf",
        lambda session_token, csrf_token, db_path: False,
    )

    response = client.post("/organization/update")

    assert response.status_code == 403
    assert response.get_json()["error"] == "INVALID_CSRF_TOKEN"


def test_state_changing_request_accepts_valid_csrf_token(
    client,
    monkeypatch,
):
    set_active_session(monkeypatch, "ORGANIZATION")
    client.set_cookie(SESSION_COOKIE, "valid-token")

    csrf_calls = []

    def fake_verify_csrf(session_token, csrf_token, db_path):
        csrf_calls.append((session_token, csrf_token, db_path))
        return True

    monkeypatch.setattr(
        auth,
        "verify_session_csrf",
        fake_verify_csrf,
    )

    response = client.post(
        "/organization/update",
        headers={"X-CSRF-Token": "valid-csrf-token"},
    )

    assert response.status_code == 200
    assert response.get_json()["message"] == "update accepted"
    assert csrf_calls == [
        ("valid-token", "valid-csrf-token", "test.db")
    ]


def test_invalid_role_configuration_raises_error():
    with pytest.raises(ValueError):
        auth.require_roles("SUPERUSER")
