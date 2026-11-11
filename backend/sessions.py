
from datetime import timedelta
from pathlib import Path

from backend.config import load_admin_config
from backend.db import DATABASE_PATH, connect_database
from backend.session_tokens import (
    generate_token,
    hash_token,
    verify_token,
)
from backend.timeutil import parse_utc, utc_now


SESSION_LIFETIME = timedelta(hours=8)


class SessionError(RuntimeError):
    """Raised when a session cannot be created or managed."""


def create_session(
    principal_type: str,
    principal_id: str,
    organization_id: str | None = None,
    db_path: Path | str = DATABASE_PATH,
) -> dict[str, str]:
    """Create an eight-hour server-side session."""

    if principal_type not in ("ORGANIZATION", "ADMIN"):
        raise ValueError("Invalid principal type.")

    if not isinstance(principal_id, str) or not principal_id.strip():
        raise ValueError("Principal ID must be a non-empty string.")

    principal_id = principal_id.strip()

    if principal_type == "ORGANIZATION":
        if organization_id != principal_id:
            raise ValueError("Organization identity does not match.")

    else:
        if organization_id is not None:
            raise ValueError("Admin sessions cannot have an organization ID.")

        config = load_admin_config()

        if principal_id != config.admin_id:
            raise SessionError("Admin identity is not configured.")

    created_at = utc_now()
    expires_at = (
        parse_utc(created_at) + SESSION_LIFETIME
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    session_token = generate_token()
    csrf_token = generate_token()

    connection = connect_database(db_path)

    try:
        connection.execute("BEGIN IMMEDIATE")

        if principal_type == "ORGANIZATION":
            organization = connection.execute(
                """
                SELECT status
                FROM Organizations
                WHERE organization_id = ?
                """,
                (organization_id,),
            ).fetchone()

            if organization is None or organization["status"] != "ACTIVE":
                raise SessionError("Organization is not active.")

        connection.execute(
            """
            INSERT INTO Sessions (
                session_token_hash,
                csrf_token_hash,
                principal_type,
                principal_id,
                organization_id,
                created_at,
                expires_at,
                revoked_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                hash_token(session_token),
                hash_token(csrf_token),
                principal_type,
                principal_id,
                organization_id,
                created_at,
                expires_at,
            ),
        )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()

    return {
        "session_token": session_token,
        "csrf_token": csrf_token,
        "expires_at": expires_at,
    }


def get_active_session(
    session_token: str,
    db_path: Path | str = DATABASE_PATH,
) -> dict | None:
    """Return an authenticated session, or None if it is invalid."""

    try:
        token_hash = hash_token(session_token)
    except (TypeError, ValueError):
        return None

    now = utc_now()
    connection = connect_database(db_path)

    try:
        row = connection.execute(
            """
            SELECT
                session_token_hash,
                csrf_token_hash,
                principal_type,
                principal_id,
                organization_id,
                created_at,
                expires_at,
                revoked_at
            FROM Sessions
            WHERE session_token_hash = ?
            """,
            (token_hash,),
        ).fetchone()

        if row is None or row["revoked_at"] is not None:
            return None

        try:
            created = parse_utc(row["created_at"])
            expires = parse_utc(row["expires_at"])
            current = parse_utc(now)
        except (TypeError, ValueError):
            return None

        if expires <= current or expires <= created:
            return None

        if row["principal_type"] == "ORGANIZATION":
            organization = connection.execute(
                """
                SELECT status
                FROM Organizations
                WHERE organization_id = ?
                """,
                (row["organization_id"],),
            ).fetchone()

            if organization is None or organization["status"] != "ACTIVE":
                return None

        elif row["principal_type"] == "ADMIN":
            try:
                config = load_admin_config()
            except Exception:
                return None

            if row["principal_id"] != config.admin_id:
                return None

        else:
            return None

        return dict(row)

    finally:
        connection.close()


def verify_session_csrf(
    session_token: str,
    csrf_token: str,
    db_path: Path | str = DATABASE_PATH,
) -> bool:
    """Verify a CSRF token against an active session."""

    session = get_active_session(session_token, db_path)

    if session is None:
        return False

    return verify_token(
        csrf_token,
        session["csrf_token_hash"],
    )


def revoke_session(
    session_token: str,
    db_path: Path | str = DATABASE_PATH,
) -> bool:
    """Revoke an active session. Return whether a row was updated."""

    try:
        token_hash = hash_token(session_token)
    except (TypeError, ValueError):
        return False

    connection = connect_database(db_path)

    try:
        connection.execute("BEGIN IMMEDIATE")

        cursor = connection.execute(
            """
            UPDATE Sessions
            SET revoked_at = ?
            WHERE session_token_hash = ?
              AND revoked_at IS NULL
            """,
            (utc_now(), token_hash),
        )

        connection.commit()
        return cursor.rowcount == 1

    except Exception:
        connection.rollback()
        raise

    finally:
        connection.close()
