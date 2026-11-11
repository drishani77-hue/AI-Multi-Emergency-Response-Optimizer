
import sqlite3

import pytest

from backend.sessions import (
    SessionError,
    create_session,
    get_active_session,
    revoke_session,
    verify_session_csrf,
)
from backend.session_tokens import hash_token
from backend.timeutil import utc_now


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
                "test-password-hash",
                "ACTIVE",
            ),
        )

        connection.commit()

    finally:
        connection.close()

    return path


@pytest.fixture
def admin_environment(monkeypatch):
    """Provide isolated Admin configuration for tests."""

    monkeypatch.setenv("RESQTECH_ADMIN_ID", "ADMIN001")
    monkeypatch.setenv("RESQTECH_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv(
        "RESQTECH_ADMIN_PASSWORD_HASH",
        "test-password-hash",
    )


def test_create_organization_session(db_path):
    session = create_session(
        "ORGANIZATION",
        "ORG001",
        "ORG001",
        db_path,
    )

    assert session["session_token"]
    assert session["csrf_token"]
    assert session["expires_at"]

    stored = get_active_session(
        session["session_token"],
        db_path,
    )

    assert stored is not None
    assert stored["principal_type"] == "ORGANIZATION"
    assert stored["principal_id"] == "ORG001"


def test_create_admin_session(db_path, admin_environment):
    session = create_session(
        "ADMIN",
        "ADMIN001",
        db_path=db_path,
    )

    stored = get_active_session(
        session["session_token"],
        db_path,
    )

    assert stored is not None
    assert stored["principal_type"] == "ADMIN"
    assert stored["principal_id"] == "ADMIN001"
    assert stored["organization_id"] is None


def test_reject_inactive_organization(db_path):
    connection = sqlite3.connect(db_path)

    try:
        connection.execute(
            """
            UPDATE Organizations
            SET status = 'INACTIVE'
            WHERE organization_id = ?
            """,
            ("ORG001",),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(SessionError):
        create_session(
            "ORGANIZATION",
            "ORG001",
            "ORG001",
            db_path,
        )


def test_reject_unknown_organization(db_path):
    with pytest.raises(SessionError):
        create_session(
            "ORGANIZATION",
            "UNKNOWN",
            "UNKNOWN",
            db_path,
        )


def test_reject_mismatched_organization_identity(db_path):
    with pytest.raises(ValueError):
        create_session(
            "ORGANIZATION",
            "ORG001",
            "ORG999",
            db_path,
        )


def test_reject_invalid_principal_type(db_path):
    with pytest.raises(ValueError):
        create_session(
            "UNKNOWN",
            "ORG001",
            db_path=db_path,
        )


def test_reject_admin_with_wrong_identity(db_path, admin_environment):
    with pytest.raises(SessionError):
        create_session(
            "ADMIN",
            "WRONG_ADMIN",
            db_path=db_path,
        )


def test_reject_admin_with_organization_id(
    db_path,
    admin_environment,
):
    with pytest.raises(ValueError):
        create_session(
            "ADMIN",
            "ADMIN001",
            "ORG001",
            db_path,
        )


def test_csrf_verification_success(db_path):
    session = create_session(
        "ORGANIZATION",
        "ORG001",
        "ORG001",
        db_path,
    )

    assert verify_session_csrf(
        session["session_token"],
        session["csrf_token"],
        db_path,
    )


def test_csrf_verification_rejects_wrong_token(db_path):
    session = create_session(
        "ORGANIZATION",
        "ORG001",
        "ORG001",
        db_path,
    )

    assert not verify_session_csrf(
        session["session_token"],
        "invalid-token",
        db_path,
    )


def test_csrf_verification_rejects_wrong_session(db_path):
    assert not verify_session_csrf(
        "invalid-token",
        "invalid-token",
        db_path,
    )


def test_session_revocation(db_path):
    session = create_session(
        "ORGANIZATION",
        "ORG001",
        "ORG001",
        db_path,
    )

    assert revoke_session(
        session["session_token"],
        db_path,
    )

    assert get_active_session(
        session["session_token"],
        db_path,
    ) is None


def test_revocation_is_idempotent(db_path):
    session = create_session(
        "ORGANIZATION",
        "ORG001",
        "ORG001",
        db_path,
    )

    assert revoke_session(session["session_token"], db_path)
    assert not revoke_session(session["session_token"], db_path)


def test_invalid_token_returns_none(db_path):
    assert get_active_session("invalid-token", db_path) is None


def test_malformed_token_cannot_be_revoked(db_path):
    assert not revoke_session("invalid-token", db_path)


def test_expired_session_is_rejected(db_path):
    session = create_session(
        "ORGANIZATION",
        "ORG001",
        "ORG001",
        db_path,
    )

    connection = sqlite3.connect(db_path)

    try:
        connection.execute(
            """
            UPDATE Sessions
            SET
                created_at = '2000-01-01T00:00:00Z',
                expires_at = '2000-01-01T08:00:00Z'
            WHERE session_token_hash = ?
            """,
            (hash_token(session["session_token"]),),
        )
        connection.commit()
    finally:
        connection.close()

    assert get_active_session(
        session["session_token"],
        db_path,
    ) is None


def test_inactive_organization_invalidates_existing_session(db_path):
    session = create_session(
        "ORGANIZATION",
        "ORG001",
        "ORG001",
        db_path,
    )

    connection = sqlite3.connect(db_path)

    try:
        connection.execute(
            """
            UPDATE Organizations
            SET status = 'INACTIVE'
            WHERE organization_id = ?
            """,
            ("ORG001",),
        )
        connection.commit()
    finally:
        connection.close()

    assert get_active_session(
        session["session_token"],
        db_path,
    ) is None


def test_session_hash_is_not_stored_as_raw_token(db_path):
    session = create_session(
        "ORGANIZATION",
        "ORG001",
        "ORG001",
        db_path,
    )

    connection = sqlite3.connect(db_path)

    try:
        row = connection.execute(
            """
            SELECT session_token_hash, csrf_token_hash
            FROM Sessions
            """
        ).fetchone()
    finally:
        connection.close()

    assert row is not None
    assert row[0] == hash_token(session["session_token"])
    assert row[1] == hash_token(session["csrf_token"])
    assert session["session_token"] not in row
    assert session["csrf_token"] not in row
