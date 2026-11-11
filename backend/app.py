
import re
import secrets
import sqlite3

from collections import defaultdict, deque
from base64 import b64decode
from datetime import datetime, timezone
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit

from flask import Flask, g, jsonify, make_response, request

from backend.config import load_admin_config
from backend.db import DATABASE_PATH, connect_database
from backend.security import (
    hash_password,
    validate_password,
    verify_password,
)
from backend.sessions import (
    create_session,
    get_active_session,
    revoke_session,
    verify_session_csrf,
)


SESSION_COOKIE = "resqtech_session"
CSRF_COOKIE = "resqtech_csrf"
SESSION_MAX_AGE = 8 * 60 * 60

RATE_LIMIT_ATTEMPTS = 5
RATE_LIMIT_WINDOW = 15 * 60

ORGANIZATION_TYPES = {
    "HOSPITAL_MEDICAL",
    "FIRE_SERVICE",
    "POLICE_SECURITY",
    "RESCUE_DISASTER_RESPONSE",
}

ORGANIZATION_OWNERSHIPS = {
    "GOVERNMENT",
    "PRIVATE",
}

EMAIL_PATTERN = re.compile(
    r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
)

_failed_attempts = defaultdict(deque)
_rate_limit_lock = Lock()


def _registration_error(error, message, status):
    """Return a consistent organization-registration error."""

    return jsonify({
        "error": error,
        "message": message,
    }), status


def _valid_password_hash(encoded_hash):
    """Validate the configured PBKDF2 hash format and parameters."""

    if not isinstance(encoded_hash, str):
        return False

    parts = encoded_hash.split("$")

    if len(parts) != 4:
        return False

    algorithm, iterations, salt_text, digest_text = parts

    if algorithm != "pbkdf2_sha256" or iterations != "600000":
        return False

    try:
        salt = b64decode(salt_text, validate=True)
        digest = b64decode(digest_text, validate=True)
    except Exception:
        return False

    return (
        len(salt) == 16
        and len(digest) == 32
        and bool(salt_text)
        and bool(digest_text)
    )


def _validate_frontend_origin(origin):
    """Reject invalid or non-origin frontend configuration."""

    if not isinstance(origin, str) or not origin.strip():
        raise RuntimeError("RESQTECH_FRONTEND_ORIGIN is required.")

    parsed = urlsplit(origin)

    if (
        parsed.scheme not in ("http", "https")
        or not parsed.netloc
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or origin != origin.strip()
    ):
        raise RuntimeError("RESQTECH_FRONTEND_ORIGIN is invalid.")

    return origin.rstrip("/")


def _validate_admin_configuration(db_path):
    """Fail startup if Admin configuration conflicts with the database."""

    admin = load_admin_config()

    if not _valid_password_hash(admin.password_hash):
        raise RuntimeError(
            "Configured Admin password hash has an invalid format."
        )

    connection = connect_database(db_path)

    try:
        collision = connection.execute(
            """
            SELECT 1
            FROM Organizations
            WHERE lower(trim(email)) = ?
            LIMIT 1
            """,
            (admin.email,),
        ).fetchone()

        if collision is not None:
            raise RuntimeError(
                "Admin email conflicts with a registered organization."
            )
    finally:
        connection.close()

    return admin


def _is_rate_limited(ip_address):
    """Check the process-local rolling login failure window."""

    now = monotonic()

    with _rate_limit_lock:
        attempts = _failed_attempts[ip_address]

        while attempts and now - attempts[0] >= RATE_LIMIT_WINDOW:
            attempts.popleft()

        return len(attempts) >= RATE_LIMIT_ATTEMPTS


def _record_failed_login(ip_address):
    now = monotonic()

    with _rate_limit_lock:
        attempts = _failed_attempts[ip_address]

        while attempts and now - attempts[0] >= RATE_LIMIT_WINDOW:
            attempts.popleft()

        attempts.append(now)


def _clear_failed_logins(ip_address):
    with _rate_limit_lock:
        _failed_attempts.pop(ip_address, None)


def create_app(test_config=None):
    """Create and configure the ResQTech Flask application."""

    # Local import avoids the auth.py -> app.py circular import.
    from backend.auth import require_roles

    app = Flask(__name__)

    app.config.update(
        DATABASE_PATH=DATABASE_PATH,
        FRONTEND_ORIGIN=None,
        SESSION_COOKIE_SECURE=None,
    )

    if test_config:
        app.config.update(test_config)

    if app.config["FRONTEND_ORIGIN"] is None:
        import os

        app.config["FRONTEND_ORIGIN"] = os.environ.get(
            "RESQTECH_FRONTEND_ORIGIN",
            "http://localhost:5173",
        )

    app.config["FRONTEND_ORIGIN"] = _validate_frontend_origin(
        app.config["FRONTEND_ORIGIN"]
    )

    admin = _validate_admin_configuration(
        app.config["DATABASE_PATH"]
    )

    app.extensions["resqtech_admin"] = admin

    @app.before_request
    def validate_request_origin():
        """Validate Origin on all state-changing browser requests."""

        if request.method == "OPTIONS":
            return None

        if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
            return None

        origin = request.headers.get("Origin")

        if origin != app.config["FRONTEND_ORIGIN"]:
            return jsonify({
                "error": "INVALID_ORIGIN",
                "message": "Request origin is not permitted.",
            }), 403

        return None

    @app.after_request
    def add_cors_headers(response):
        """Allow credentialed requests from the configured origin only."""

        origin = request.headers.get("Origin")

        if origin == app.config["FRONTEND_ORIGIN"]:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, X-CSRF-Token"
            )
            response.headers["Access-Control-Allow-Methods"] = (
                "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            )
            response.headers.add("Vary", "Origin")

        return response

    @app.route("/organization", methods=["POST"])
    def register_organization():
        """Register an organization without automatically logging it in."""

        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return _registration_error(
                "INVALID_REQUEST",
                "A JSON request body is required.",
                400,
            )

        allowed_fields = {
            "name",
            "organization_type",
            "ownership",
            "phone",
            "email",
            "password",
        }

        required_fields = {
            "name",
            "organization_type",
            "ownership",
            "email",
            "password",
        }

        if set(data) - allowed_fields:
            return _registration_error(
                "INVALID_REQUEST",
                "The request contains unsupported fields.",
                400,
            )

        if not required_fields.issubset(data):
            return _registration_error(
                "INVALID_REQUEST",
                "All required organization fields must be provided.",
                400,
            )

        for field in required_fields:
            if not isinstance(data[field], str):
                return _registration_error(
                    "INVALID_REQUEST",
                    f"{field} must be a string.",
                    400,
                )

        name = data["name"].strip()
        organization_type = data["organization_type"]
        ownership = data["ownership"]
        email = data["email"].strip().lower()
        password = data["password"]

        phone = data.get("phone")

        if phone is not None:
            if not isinstance(phone, str):
                return _registration_error(
                    "INVALID_REQUEST",
                    "phone must be a string.",
                    400,
                )

            phone = phone.strip() or None

        if not name:
            return _registration_error(
                "INVALID_REQUEST",
                "Organization name cannot be empty.",
                400,
            )

        if organization_type not in ORGANIZATION_TYPES:
            return _registration_error(
                "INVALID_ORGANIZATION_TYPE",
                "The selected organization type is not supported.",
                400,
            )

        if ownership not in ORGANIZATION_OWNERSHIPS:
            return _registration_error(
                "INVALID_OWNERSHIP",
                "Ownership must be GOVERNMENT or PRIVATE.",
                400,
            )

        if (
            not email
            or len(email) > 254
            or not email.isascii()
            or not EMAIL_PATTERN.fullmatch(email)
        ):
            return _registration_error(
                "INVALID_EMAIL",
                "A valid ASCII email address is required.",
                400,
            )

        try:
            validate_password(password)
        except (TypeError, ValueError):
            return _registration_error(
                "INVALID_PASSWORD",
                "Password must contain between 12 and 128 characters.",
                400,
            )

        if email == admin.email:
            return _registration_error(
                "EMAIL_ALREADY_REGISTERED",
                "This email address is already registered.",
                409,
            )

        db_path = app.config["DATABASE_PATH"]
        connection = connect_database(db_path)

        try:
            existing = connection.execute(
                """
                SELECT 1
                FROM Organizations
                WHERE lower(trim(email)) = ?
                LIMIT 1
                """,
                (email,),
            ).fetchone()

            if existing is not None:
                return _registration_error(
                    "EMAIL_ALREADY_REGISTERED",
                    "This email address is already registered.",
                    409,
                )

            password_hash = hash_password(password)

            for attempt in range(3):
                organization_id = f"org_{secrets.token_hex(8)}"

                try:
                    connection.execute("BEGIN IMMEDIATE")

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
                        VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE')
                        """,
                        (
                            organization_id,
                            name,
                            organization_type,
                            ownership,
                            phone,
                            email,
                            password_hash,
                        ),
                    )

                    connection.commit()

                    return jsonify({
                        "organization_id": organization_id,
                        "name": name,
                        "status": "ACTIVE",
                    }), 201

                except sqlite3.IntegrityError:
                    connection.rollback()

                    existing = connection.execute(
                        """
                        SELECT 1
                        FROM Organizations
                        WHERE lower(trim(email)) = ?
                        LIMIT 1
                        """,
                        (email,),
                    ).fetchone()

                    if existing is not None:
                        return _registration_error(
                            "EMAIL_ALREADY_REGISTERED",
                            "This email address is already registered.",
                            409,
                        )

                    if attempt == 2:
                        app.logger.exception(
                            "Organization registration integrity failure."
                        )

                except sqlite3.Error:
                    connection.rollback()
                    app.logger.exception(
                        "Organization registration database failure."
                    )

                    return _registration_error(
                        "REGISTRATION_UNAVAILABLE",
                        "Unable to complete organization registration.",
                        500,
                    )

            return _registration_error(
                "REGISTRATION_UNAVAILABLE",
                "Unable to generate a unique organization ID.",
                500,
            )

        except sqlite3.Error:
            app.logger.exception(
                "Organization registration database failure."
            )

            return _registration_error(
                "REGISTRATION_UNAVAILABLE",
                "Unable to complete organization registration.",
                500,
            )

        finally:
            connection.close()

    @app.route("/resource", methods=["POST"])
    @require_roles("ORGANIZATION")
    def create_resource():
        """Register a resource for the authenticated organization."""

        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify({
                "error": "INVALID_REQUEST",
                "message": "A JSON request body is required.",
            }), 400

        allowed_fields = {
            "resource_type",
            "base_location_id",
            "status",
        }

        if set(data) != allowed_fields:
            return jsonify({
                "error": "INVALID_REQUEST",
                "message": (
                    "Exactly resource_type, base_location_id "
                    "and status must be provided."
                ),
            }), 400

        resource_types = {
            "AMBULANCE",
            "FIRE_VEHICLE",
            "POLICE_UNIT",
            "RESCUE_VEHICLE",
        }

        # REQUESTED and DISPATCHED belong to the allocation lifecycle.
        # INACTIVE is handled by the resource deactivation lifecycle.
        initial_statuses = {"AVAILABLE", "UNAVAILABLE"}

        resource_type = data["resource_type"]
        base_location_id = data["base_location_id"]
        status = data["status"]

        if (
            not isinstance(resource_type, str)
            or resource_type not in resource_types
        ):
            return jsonify({
                "error": "INVALID_RESOURCE_TYPE",
                "message": "The resource type is not supported.",
            }), 400

        if (
            not isinstance(base_location_id, str)
            or not base_location_id.strip()
        ):
            return jsonify({
                "error": "INVALID_BASE_LOCATION",
                "message": "A valid base location is required.",
            }), 400

        base_location_id = base_location_id.strip()

        if (
            not isinstance(status, str)
            or status not in initial_statuses
        ):
            return jsonify({
                "error": "INVALID_RESOURCE_STATUS",
                "message": (
                    "Initial status must be AVAILABLE or UNAVAILABLE."
                ),
            }), 400

        organization_id = g.resqtech_principal["organization_id"]
        db_path = app.config["DATABASE_PATH"]
        connection = connect_database(db_path)

        try:
            connection.execute("BEGIN IMMEDIATE")

            organization = connection.execute(
                """
                SELECT status
                FROM Organizations
                WHERE organization_id = ?
                """,
                (organization_id,),
            ).fetchone()

            if organization is None or organization["status"] != "ACTIVE":
                connection.rollback()

                return jsonify({
                    "error": "NOT_ACTIVE",
                    "message": "The organization is not active.",
                }), 409

            location = connection.execute(
                """
                SELECT 1
                FROM Locations
                WHERE location_id = ?
                """,
                (base_location_id,),
            ).fetchone()

            if location is None:
                connection.rollback()

                return jsonify({
                    "error": "LOCATION_NOT_FOUND",
                    "message": "The specified base location does not exist.",
                }), 404

            last_updated = (
                datetime.now(timezone.utc)
                .replace(microsecond=0)
                .strftime("%Y-%m-%dT%H:%M:%SZ")
            )

            resource_id = None

            for _ in range(3):
                candidate_id = f"res_{secrets.token_hex(8)}"

                try:
                    connection.execute(
                        """
                        INSERT INTO Resources (
                            resource_id,
                            organization_id,
                            resource_type,
                            base_location_id,
                            last_reported_location_id,
                            status,
                            last_updated
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            candidate_id,
                            organization_id,
                            resource_type,
                            base_location_id,
                            base_location_id,
                            status,
                            last_updated,
                        ),
                    )

                    resource_id = candidate_id
                    break

                except sqlite3.IntegrityError:
                    existing = connection.execute(
                        """
                        SELECT 1
                        FROM Resources
                        WHERE resource_id = ?
                        """,
                        (candidate_id,),
                    ).fetchone()

                    if existing is None:
                        raise

            if resource_id is None:
                connection.rollback()

                return jsonify({
                    "error": "RESOURCE_REGISTRATION_UNAVAILABLE",
                    "message": "Unable to generate a unique resource ID.",
                }), 500

            connection.commit()

            return jsonify({
                "resource_id": resource_id,
                "resource_type": resource_type,
                "base_location_id": base_location_id,
                "last_reported_location_id": base_location_id,
                "status": status,
                "last_updated": last_updated,
            }), 201

        except sqlite3.Error:
            connection.rollback()

            app.logger.exception(
                "Resource registration database failure."
            )

            return jsonify({
                "error": "RESOURCE_REGISTRATION_UNAVAILABLE",
                "message": "Unable to register the resource.",
            }), 500

        finally:
            connection.close()

    @app.route("/auth/login", methods=["POST"])
    def login():
        """Authenticate an organization or the configured Admin."""

        ip_address = request.remote_addr or "unknown"

        if _is_rate_limited(ip_address):
            return jsonify({
                "error": "RATE_LIMITED",
                "message": "Too many failed login attempts. Try again later.",
            }), 429

        data = request.get_json(silent=True)

        if not isinstance(data, dict):
            return jsonify({
                "error": "INVALID_REQUEST",
                "message": "A JSON request body is required.",
            }), 400

        email = data.get("email")
        password = data.get("password")

        if (
            not isinstance(email, str)
            or not isinstance(password, str)
            or not email.strip()
            or not password
        ):
            return jsonify({
                "error": "INVALID_REQUEST",
                "message": "Email and password are required.",
            }), 400

        email = email.strip().lower()

        if len(email) > 254 or len(password) > 128:
            _record_failed_login(ip_address)
            return jsonify({
                "error": "INVALID_CREDENTIALS",
                "message": "Invalid email or password.",
            }), 401

        db_path = app.config["DATABASE_PATH"]
        principal_type = None
        principal_id = None
        organization_id = None
        identity = None

        # Check the configured Admin account first.
        if email == admin.email:
            if verify_password(password, admin.password_hash):
                principal_type = "ADMIN"
                principal_id = admin.admin_id
                identity = {
                    "admin_id": admin.admin_id,
                }

        else:
            connection = connect_database(db_path)

            try:
                organization = connection.execute(
                    """
                    SELECT
                        organization_id,
                        name,
                        status,
                        password_hash
                    FROM Organizations
                    WHERE lower(trim(email)) = ?
                    LIMIT 1
                    """,
                    (email,),
                ).fetchone()
            finally:
                connection.close()

            if organization is not None:
                password_matches = verify_password(
                    password,
                    organization["password_hash"],
                )

                if (
                    password_matches
                    and organization["status"] == "ACTIVE"
                ):
                    principal_type = "ORGANIZATION"
                    principal_id = organization["organization_id"]
                    organization_id = organization["organization_id"]

                    identity = {
                        "organization_id": organization["organization_id"],
                        "name": organization["name"],
                    }

        if principal_type is None:
            _record_failed_login(ip_address)

            return jsonify({
                "error": "INVALID_CREDENTIALS",
                "message": "Invalid email or password.",
            }), 401

        try:
            tokens = create_session(
                principal_type=principal_type,
                principal_id=principal_id,
                organization_id=organization_id,
                db_path=db_path,
            )
        except Exception:
            app.logger.exception("Session creation failed.")

            return jsonify({
                "error": "AUTHENTICATION_UNAVAILABLE",
                "message": "Unable to complete login.",
            }), 500

        _clear_failed_logins(ip_address)

        response_data = {"role": principal_type}

        if principal_type == "ORGANIZATION":
            response_data["organization"] = identity
        else:
            response_data["admin"] = identity

        response = make_response(jsonify(response_data), 200)

        secure_cookie = (
            request.is_secure
            if app.config["SESSION_COOKIE_SECURE"] is None
            else app.config["SESSION_COOKIE_SECURE"]
        )

        response.set_cookie(
            SESSION_COOKIE,
            tokens["session_token"],
            max_age=SESSION_MAX_AGE,
            httponly=True,
            secure=secure_cookie,
            samesite="Lax",
            path="/",
        )

        response.set_cookie(
            CSRF_COOKIE,
            tokens["csrf_token"],
            max_age=SESSION_MAX_AGE,
            httponly=False,
            secure=secure_cookie,
            samesite="Lax",
            path="/",
        )

        return response

    @app.route("/auth/logout", methods=["POST"])
    def logout():
        """Revoke the current session after CSRF verification."""

        session_token = request.cookies.get(SESSION_COOKIE)
        csrf_token = request.headers.get("X-CSRF-Token")
        db_path = app.config["DATABASE_PATH"]

        if not session_token:
            return jsonify({
                "error": "UNAUTHENTICATED",
                "message": "Authentication is required.",
            }), 401

        active_session = get_active_session(
            session_token,
            db_path,
        )

        if active_session is None:
            return jsonify({
                "error": "UNAUTHENTICATED",
                "message": "Authentication is required.",
            }), 401

        if not csrf_token or not verify_session_csrf(
            session_token,
            csrf_token,
            db_path,
        ):
            return jsonify({
                "error": "INVALID_CSRF_TOKEN",
                "message": "CSRF verification failed.",
            }), 403

        if not revoke_session(session_token, db_path):
            return jsonify({
                "error": "LOGOUT_FAILED",
                "message": "Unable to revoke the session.",
            }), 500

        response = make_response(jsonify({"ok": True}), 200)

        secure_cookie = (
            request.is_secure
            if app.config["SESSION_COOKIE_SECURE"] is None
            else app.config["SESSION_COOKIE_SECURE"]
        )

        response.set_cookie(
            SESSION_COOKIE,
            "",
            max_age=0,
            httponly=True,
            secure=secure_cookie,
            samesite="Lax",
            path="/",
        )

        response.set_cookie(
            CSRF_COOKIE,
            "",
            max_age=0,
            httponly=False,
            secure=secure_cookie,
            samesite="Lax",
            path="/",
        )

        return response

    return app
