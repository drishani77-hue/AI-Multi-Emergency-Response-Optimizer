
import re
import secrets
import sqlite3

import json
import uuid

from datetime import datetime, timedelta, timezone
from backend.emergency_triage import evaluate_emergency
from collections import defaultdict, deque
from base64 import b64decode
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
_road_engine_init_lock = Lock()


def get_road_engine(app):
    """Return the application's shared road engine, initializing it once."""

    engine = app.extensions.get("resqtech_road_engine")

    if engine is not None:
        return engine

    with _road_engine_init_lock:
        engine = app.extensions.get("resqtech_road_engine")

        if engine is not None:
            return engine

        from backend.road_engine import RoadEngine

        engine = RoadEngine()
        app.extensions["resqtech_road_engine"] = engine

        return engine


_allocation_coordinator_init_lock = Lock()


def get_allocation_coordinator(app):
    """Return the application's shared allocation coordinator."""

    coordinator = app.extensions.get("resqtech_allocation_coordinator")
    if coordinator is not None:
        return coordinator

    with _allocation_coordinator_init_lock:
        coordinator = app.extensions.get("resqtech_allocation_coordinator")
        if coordinator is not None:
            return coordinator

        from backend.allocation_coordinator import AllocationCoordinator

        coordinator = AllocationCoordinator(
            app.config["DATABASE_PATH"],
            get_road_engine(app),
        )
        app.extensions["resqtech_allocation_coordinator"] = coordinator
        return coordinator


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
    @app.route("/emergency", methods=["POST"])
    def report_emergency():
        """Accept and persist a citizen or bystander emergency report."""

        data = request.get_json(silent=True)

        def error_response(error, message, status):
            return jsonify({
                "error": error,
                "message": message,
            }), status

        if not isinstance(data, dict):
            return error_response(
                "INVALID_REQUEST",
                "A JSON request body is required.",
                400,
            )

        allowed_fields = {
            "emergency_type",
            "location_id",
            "location_text",
            "assessment_answers",
            "description",
            "reporter_name",
            "reporter_phone",
            "reporter_type",
            "additional_details",
            "idempotency_key",
        }

        if set(data) - allowed_fields:
            return error_response(
                "INVALID_REQUEST",
                "The request contains unsupported fields.",
                400,
            )

        required_fields = {
            "emergency_type",
            "location_text",
            "assessment_answers",
            "description",
            "reporter_name",
            "reporter_phone",
            "reporter_type",
            "idempotency_key",
        }

        if not required_fields.issubset(data):
            return error_response(
                "INVALID_REQUEST",
                "All required emergency-report fields must be provided.",
                400,
            )

        text_fields = (
            "emergency_type",
            "location_text",
            "description",
            "reporter_name",
            "reporter_phone",
            "reporter_type",
            "idempotency_key",
        )

        if any(not isinstance(data[field], str) for field in text_fields):
            return error_response(
                "INVALID_REQUEST",
                "Text fields must contain strings.",
                400,
            )

        emergency_type = data["emergency_type"].strip().upper()
        location_text = data["location_text"].strip()
        description = data["description"].strip()
        reporter_name = data["reporter_name"].strip()
        reporter_type = data["reporter_type"].strip().upper()
        idempotency_key = data["idempotency_key"].strip()

        additional_details = data.get("additional_details", "")

        if additional_details is None:
            additional_details = ""

        if not isinstance(additional_details, str):
            return error_response(
                "INVALID_REQUEST",
                "additional_details must be a string.",
                400,
            )

        additional_details = additional_details.strip()

        if not isinstance(data["assessment_answers"], dict):
            return error_response(
                "INVALID_ASSESSMENT",
                "assessment_answers must be a JSON object.",
                400,
            )

        supported_types = {
            "MEDICAL_EMERGENCY",
            "FIRE",
            "ROAD_TRAFFIC_ACCIDENT",
            "THREAT_TO_LIFE_VIOLENCE",
            "TRAPPED_PERSON_RESCUE",
        }

        supported_reporter_types = {
            "CITIZEN",
            "BYSTANDER",
            "AUTHORIZED_EMERGENCY_OPERATOR",
        }

        if emergency_type not in supported_types:
            return error_response(
                "INVALID_EMERGENCY_TYPE",
                "The emergency type is not supported.",
                400,
            )

        if reporter_type not in supported_reporter_types:
            return error_response(
                "INVALID_REPORTER_TYPE",
                "The reporter type is not supported.",
                400,
            )

        try:
            uuid.UUID(idempotency_key)
        except (ValueError, AttributeError):
            return error_response(
                "INVALID_IDEMPOTENCY_KEY",
                "A valid UUID idempotency key is required.",
                400,
            )

        word_count = len(description.split())

        if not 5 <= word_count <= 300:
            return error_response(
                "INVALID_DESCRIPTION",
                "Description must contain between 5 and 300 words.",
                400,
            )

        if not location_text or not reporter_name:
            return error_response(
                "INVALID_REQUEST",
                "Location and reporter name cannot be empty.",
                400,
            )

        if len(reporter_name) > 150 or len(location_text) > 500:
            return error_response(
                "INVALID_REQUEST",
                "A text field exceeds its permitted length.",
                400,
            )

        phone = reporter_phone = data["reporter_phone"].strip()

        phone = re.sub(r"[ ()-]", "", phone)

        if phone.startswith("+91"):
            phone = phone[3:]

        if not re.fullmatch(r"[0-9]{10}", phone):
            return error_response(
                "INVALID_PHONE",
                "Enter a valid 10-digit Indian phone number.",
                400,
            )

        location_id = data.get("location_id")

        if location_id is not None:
            if not isinstance(location_id, str) or not location_id.strip():
                return error_response(
                    "INVALID_LOCATION",
                    "location_id must be a non-empty string or null.",
                    400,
                )

            location_id = location_id.strip()

        answers = data["assessment_answers"]

        try:
            triage = evaluate_emergency(emergency_type, answers)
        except (TypeError, ValueError, KeyError) as exc:
            return error_response(
                "INVALID_ASSESSMENT",
                str(exc),
                400,
            )

        normalized_answers = triage["assessment_answers"]

        answers_json = json.dumps(
            normalized_answers,
            sort_keys=True,
            separators=(",", ":"),
        )

        db_path = app.config["DATABASE_PATH"]
        connection = connect_database(db_path)

        try:
            connection.execute("BEGIN IMMEDIATE")

            resolved_location_id = None
            location_resolved = 0

            if location_id is not None:
                location = connection.execute(
                    """
                    SELECT location_id, road_node_id
                    FROM Locations
                    WHERE location_id = ?
                    """,
                    (location_id,),
                ).fetchone()

                if location is not None and location["road_node_id"]:
                    resolved_location_id = location["location_id"]
                    location_resolved = 1

            canonical_payload = {
                "emergency_type": emergency_type,
                "location_id": resolved_location_id,
                "location_text": location_text,
                "assessment_answers": normalized_answers,
                "description": description,
                "reporter_name": reporter_name,
                "reporter_phone": phone,
                "reporter_type": reporter_type,
                "additional_details": additional_details,
            }

            existing = connection.execute(
                """
                SELECT
                    emergency_id,
                    emergency_type,
                    location_id,
                    location_text,
                    assessment_answers_json,
                    description,
                    reporter_name,
                    reporter_phone,
                    reporter_type,
                    additional_details,
                    location_resolved,
                    severity,
                    assessment_uncertain,
                    reported_at
                FROM Emergencies
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()

            if existing is not None:
                stored_payload = {
                    "emergency_type": existing["emergency_type"],
                    "location_id": existing["location_id"],
                    "location_text": existing["location_text"],
                    "assessment_answers": json.loads(
                        existing["assessment_answers_json"]
                    ),
                    "description": existing["description"],
                    "reporter_name": existing["reporter_name"],
                    "reporter_phone": existing["reporter_phone"],
                    "reporter_type": existing["reporter_type"],
                    "additional_details": existing["additional_details"],
                }

                if stored_payload != canonical_payload:
                    connection.rollback()

                    return error_response(
                        "IDEMPOTENCY_KEY_CONFLICT",
                        "This idempotency key was already used for a different report.",
                        409,
                    )

                connection.commit()

                return jsonify({
                    "emergency_id": existing["emergency_id"],
                    "status": "PENDING",
                    "severity": existing["severity"],
                    "assessment_uncertain": bool(
                        existing["assessment_uncertain"]
                    ),
                    "location_resolved": bool(
                        existing["location_resolved"]
                    ),
                    "reported_at": existing["reported_at"],
                    "message": "Emergency report received.",
                }), 200

            reported_at = (
                datetime.now(timezone.utc)
                .replace(microsecond=0)
                .strftime("%Y-%m-%dT%H:%M:%SZ")
            )

            emergency_id = f"emg_{secrets.token_hex(8)}"

            connection.execute(
                """
                INSERT INTO Emergencies (
                    emergency_id,
                    emergency_type,
                    severity,
                    location_id,
                    additional_details,
                    description,
                    reporter_name,
                    reporter_phone,
                    reporter_type,
                    reported_at,
                    status,
                    data_source,
                    idempotency_key,
                    location_text,
                    location_resolved,
                    assessment_answers_json,
                    assessment_uncertain,
                    assessment_reasons,
                    severity_rule_version
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    'PENDING', 'OPERATIONAL', ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    emergency_id,
                    emergency_type,
                    triage["severity"],
                    resolved_location_id,
                    additional_details,
                    description,
                    reporter_name,
                    phone,
                    reporter_type,
                    reported_at,
                    idempotency_key,
                    location_text,
                    location_resolved,
                    answers_json,
                    int(triage["assessment_uncertain"]),
                    json.dumps(triage["assessment_reasons"]),
                    triage["severity_rule_version"],
                ),
            )

            requirements = triage["requirements"]

            for resource_type, quantity in sorted(requirements.items()):
                if quantity <= 0:
                    continue

                group_id = f"rg_{secrets.token_hex(8)}"

                connection.execute(
                    """
                    INSERT INTO Requirement_Groups (
                        requirement_group_id,
                        emergency_id,
                        resource_type,
                        quantity_required,
                        status
                    )
                    VALUES (?, ?, ?, ?, 'PENDING')
                    """,
                    (
                        group_id,
                        emergency_id,
                        resource_type,
                        quantity,
                    ),
                )

                for unit_number in range(1, quantity + 1):
                    unit_id = f"ru_{secrets.token_hex(8)}"

                    connection.execute(
                        """
                        INSERT INTO Requirement_Units (
                            requirement_unit_id,
                            requirement_group_id,
                            unit_number,
                            resource_type,
                            status,
                            pending_since,
                            expires_at
                        )
                        VALUES (?, ?, ?, ?, 'PENDING', NULL, NULL)
                        """,
                        (
                            unit_id,
                            group_id,
                            unit_number,
                            resource_type,
                        ),
                    )

            connection.commit()

            return jsonify({
                "emergency_id": emergency_id,
                "status": "PENDING",
                "severity": triage["severity"],
                "assessment_uncertain": bool(
                    triage["assessment_uncertain"]
                ),
                "location_resolved": bool(location_resolved),
                "reported_at": reported_at,
                "message": "Emergency report received.",
            }), 201

        except sqlite3.IntegrityError:
            connection.rollback()

            # Check whether another request created this idempotency key.
            existing = connection.execute(
                """
                SELECT
                    emergency_id,
                    emergency_type,
                    location_id,
                    location_text,
                    assessment_answers_json,
                    description,
                    reporter_name,
                    reporter_phone,
                    reporter_type,
                    additional_details,
                    location_resolved,
                    severity,
                    assessment_uncertain,
                    reported_at
                FROM Emergencies
                WHERE idempotency_key = ?
                """,
                (idempotency_key,),
            ).fetchone()

            if existing is not None:
                stored_payload = {
                    "emergency_type": existing["emergency_type"],
                    "location_id": existing["location_id"],
                    "location_text": existing["location_text"],
                    "assessment_answers": json.loads(
                        existing["assessment_answers_json"]
                    ),
                    "description": existing["description"],
                    "reporter_name": existing["reporter_name"],
                    "reporter_phone": existing["reporter_phone"],
                    "reporter_type": existing["reporter_type"],
                    "additional_details": existing["additional_details"],
                }

                if stored_payload != canonical_payload:
                    return error_response(
                        "IDEMPOTENCY_KEY_CONFLICT",
                        "This idempotency key was already used for a different report.",
                        409,
                    )

                return jsonify({
                    "emergency_id": existing["emergency_id"],
                    "status": "PENDING",
                    "severity": existing["severity"],
                    "assessment_uncertain": bool(
                        existing["assessment_uncertain"]
                    ),
                    "location_resolved": bool(
                        existing["location_resolved"]
                    ),
                    "reported_at": existing["reported_at"],
                    "message": "Emergency report received.",
                }), 200

            app.logger.exception(
                "Emergency report integrity failure."
            )

            return error_response(
                "EMERGENCY_REPORT_UNAVAILABLE",
                "Unable to save the emergency report.",
                500,
            )

        except sqlite3.Error:
            connection.rollback()

            app.logger.exception(
                "Emergency report database failure."
            )

            return error_response(
                "EMERGENCY_REPORT_UNAVAILABLE",
                "Unable to save the emergency report.",
                500,
            )

        finally:
            connection.close()

    # Allocation API: organization-scoped request handling and history.

    def _allocation_error(error, message, status):
        return jsonify({"error": error, "message": message}), status

    def _allocation_json_body(allowed_fields):
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return None, _allocation_error(
                "INVALID_REQUEST", "A JSON request body is required.", 400
            )
        if set(data) - allowed_fields:
            return None, _allocation_error(
                "INVALID_REQUEST", "The request contains unsupported fields.", 400
            )
        allocation_id = data.get("allocation_id")
        if not isinstance(allocation_id, str) or not allocation_id.strip():
            return None, _allocation_error(
                "INVALID_REQUEST", "allocation_id must be a non-empty string.", 400
            )
        data["allocation_id"] = allocation_id.strip()
        return data, None

    def _allocation_current_state(allocation_id, organization_id):
        connection = connect_database(app.config["DATABASE_PATH"])
        try:
            return connection.execute(
                """
                SELECT a.status, a.response_status,
                       ru.status AS requirement_unit_status,
                       r.status AS resource_status
                FROM Allocations a
                JOIN Resources r ON r.resource_id = a.resource_id
                JOIN Requirement_Units ru
                  ON ru.requirement_unit_id = a.requirement_unit_id
                WHERE a.allocation_id = ?
                  AND r.organization_id = ?
                """,
                (allocation_id, organization_id),
            ).fetchone()
        finally:
            connection.close()

    def _allocation_coordinator_error(result):
        code = result.get("code", "ALLOCATION_ERROR")
        if code == "ALLOCATION_NOT_FOUND":
            return _allocation_error(
                "NOT_FOUND", "Allocation not found.", 404
            )
        if code == "ALLOCATION_EXPIRED":
            return _allocation_error(
                "ALLOCATION_EXPIRED", "The allocation response deadline has passed.", 409
            )
        if code in {"ALLOCATION_NOT_PENDING", "ALLOCATION_NOT_DISPATCHED"}:
            return _allocation_error(
                "ILLEGAL_STATE_TRANSITION",
                "The allocation is not in a state that permits this action.",
                409,
            )
        return _allocation_error(
            "ALLOCATION_CONFLICT", "The allocation could not be updated.", 409
        )

    @app.route("/organization/requests", methods=["GET"])
    @require_roles("ORGANIZATION")
    def organization_requests():
        organization_id = g.resqtech_principal["organization_id"]
        connection = connect_database(app.config["DATABASE_PATH"])
        try:
            rows = connection.execute(
                """
                SELECT a.allocation_id, a.emergency_id,
                       em.emergency_type, em.severity,
                       loc.district, loc.locality, loc.specific_location,
                       em.location_text, em.location_resolved,
                       em.description, ru.resource_type,
                       a.distance_km, a.requested_at, a.deadline_at,
                       a.status, a.response_status
                FROM Allocations a
                JOIN Resources r ON r.resource_id = a.resource_id
                JOIN Requirement_Units ru
                  ON ru.requirement_unit_id = a.requirement_unit_id
                JOIN Requirement_Groups rg
                  ON rg.requirement_group_id = ru.requirement_group_id
                JOIN Emergencies em ON em.emergency_id = a.emergency_id
                LEFT JOIN Locations loc ON loc.location_id = em.location_id
                WHERE r.organization_id = ?
                  AND a.status = 'REQUESTED'
                  AND a.response_status = 'PENDING'
                ORDER BY a.requested_at ASC, a.allocation_id ASC
                """,
                (organization_id,),
            ).fetchall()

            return jsonify({
                "items": [
                    {
                        "allocation_id": row["allocation_id"],
                        "emergency_id": row["emergency_id"],
                        "emergency_type": row["emergency_type"],
                        "severity": row["severity"],
                        "location": {
                            "district": row["district"],
                            "locality": row["locality"],
                            "specific_location": (
                                row["specific_location"] or row["location_text"]
                            ),
                        },
                        "description": row["description"],
                        "resource_type": row["resource_type"],
                        "distance_km": row["distance_km"],
                        "requested_at": row["requested_at"],
                        "deadline_at": row["deadline_at"],
                        "status": row["status"],
                        "response_status": row["response_status"],
                    }
                    for row in rows
                ]
            })
        finally:
            connection.close()

    @app.route("/organization/history", methods=["GET"])
    @require_roles("ORGANIZATION")
    def organization_history():
        allowed_params = {"final_status", "from", "to", "page", "page_size"}
        if set(request.args.keys()) - allowed_params:
            return _allocation_error(
                "INVALID_QUERY", "The request contains unsupported query parameters.", 400
            )

        try:
            page = int(request.args.get("page", "1"))
            page_size = int(request.args.get("page_size", "25"))
            if page < 1 or not 1 <= page_size <= 100:
                raise ValueError
        except (TypeError, ValueError):
            return _allocation_error(
                "INVALID_QUERY", "page must be positive and page_size must be 1?100.", 400
            )

        final_status = request.args.get("final_status")
        allowed_statuses = {"COMPLETED", "FAILED", "REJECTED", "TIMEOUT", "CANCELLED"}
        if final_status is not None and final_status not in allowed_statuses:
            return _allocation_error(
                "INVALID_QUERY", "final_status is not supported.", 400
            )

        date_from = request.args.get("from")
        date_to = request.args.get("to")
        for value in (date_from, date_to):
            if value is not None:
                try:
                    datetime.strptime(value, "%Y-%m-%d")
                except ValueError:
                    return _allocation_error(
                        "INVALID_QUERY", "Dates must use YYYY-MM-DD format.", 400
                    )
        if date_from and date_to and date_from > date_to:
            return _allocation_error(
                "INVALID_QUERY", "The from date cannot be after the to date.", 400
            )

        final_status_sql = """
            CASE
                WHEN a.status IN ('COMPLETED', 'FAILED') THEN a.status
                ELSE a.response_status
            END
        """
        conditions = [
            "r.organization_id = ?",
            "a.status IN ('COMPLETED', 'FAILED', 'CLOSED')",
        ]
        params = [g.resqtech_principal["organization_id"]]

        if final_status:
            conditions.append(f"{final_status_sql} = ?")
            params.append(final_status)
        if date_from:
            conditions.append("date(a.requested_at) >= date(?)")
            params.append(date_from)
        if date_to:
            conditions.append("date(a.requested_at) <= date(?)")
            params.append(date_to)

        where_sql = " AND ".join(conditions)
        connection = connect_database(app.config["DATABASE_PATH"])
        try:
            total = connection.execute(
                f"""
                SELECT COUNT(*)
                FROM Allocations a
                JOIN Resources r ON r.resource_id = a.resource_id
                WHERE {where_sql}
                """,
                params,
            ).fetchone()[0]

            rows = connection.execute(
                f"""
                SELECT a.allocation_id, a.emergency_id, a.resource_id,
                       {final_status_sql} AS final_status,
                       a.requested_at, a.dispatched_at,
                       a.completed_at, a.returned_at
                FROM Allocations a
                JOIN Resources r ON r.resource_id = a.resource_id
                WHERE {where_sql}
                ORDER BY a.requested_at DESC, a.allocation_id DESC
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()

            return jsonify({
                "items": [dict(row) for row in rows],
                "page": page,
                "page_size": page_size,
                "total_items": total,
                "total_pages": (total + page_size - 1) // page_size,
            })
        finally:
            connection.close()

    @app.route("/allocation/accept", methods=["POST"])
    @require_roles("ORGANIZATION")
    def accept_allocation():
        data, error = _allocation_json_body({"allocation_id"})
        if error:
            return error

        organization_id = g.resqtech_principal["organization_id"]
        try:
            result = get_allocation_coordinator(app).organization_response(
                data["allocation_id"], organization_id, accept=True
            )
            if not result.get("ok"):
                return _allocation_coordinator_error(result)

            state = _allocation_current_state(data["allocation_id"], organization_id)
            if state is None:
                return _allocation_error("NOT_FOUND", "Allocation not found.", 404)

            return jsonify({
                "allocation_id": data["allocation_id"],
                "status": state["status"],
                "response_status": state["response_status"],
                "requirement_unit_status": state["requirement_unit_status"],
                "resource_status": state["resource_status"],
            })
        except sqlite3.Error:
            app.logger.exception("Database error while accepting allocation.")
            return _allocation_error("ALLOCATION_UNAVAILABLE", "Unable to accept allocation.", 500)

    @app.route("/allocation/reject", methods=["POST"])
    @require_roles("ORGANIZATION")
    def reject_allocation():
        data, error = _allocation_json_body({"allocation_id", "reason"})
        if error:
            return error

        reason = data.get("reason")
        if reason is not None and not isinstance(reason, str):
            return _allocation_error("INVALID_REQUEST", "reason must be a string.", 400)
        reason = (reason or "Organization declined the request.").strip()
        if not reason:
            reason = "Organization declined the request."

        organization_id = g.resqtech_principal["organization_id"]
        try:
            result = get_allocation_coordinator(app).organization_response(
                data["allocation_id"], organization_id,
                accept=False, reason=reason,
            )
            if not result.get("ok"):
                return _allocation_coordinator_error(result)

            state = _allocation_current_state(data["allocation_id"], organization_id)
            if state is None:
                return _allocation_error("NOT_FOUND", "Allocation not found.", 404)

            return jsonify({
                "allocation_id": data["allocation_id"],
                "status": state["status"],
                "response_status": state["response_status"],
                "requirement_unit_status": state["requirement_unit_status"],
            })
        except sqlite3.Error:
            app.logger.exception("Database error while rejecting allocation.")
            return _allocation_error("ALLOCATION_UNAVAILABLE", "Unable to reject allocation.", 500)

    @app.route("/allocation/complete", methods=["POST"])
    @require_roles("ORGANIZATION")
    def complete_allocation():
        data, error = _allocation_json_body({"allocation_id"})
        if error:
            return error

        organization_id = g.resqtech_principal["organization_id"]
        try:
            result = get_allocation_coordinator(app).complete_allocation(
                data["allocation_id"], organization_id
            )
            if not result.get("ok"):
                return _allocation_coordinator_error(result)

            state = _allocation_current_state(data["allocation_id"], organization_id)
            if state is None:
                return _allocation_error("NOT_FOUND", "Allocation not found.", 404)

            return jsonify({
                "allocation_id": data["allocation_id"],
                "status": state["status"],
                "response_status": state["response_status"],
                "requirement_unit_status": state["requirement_unit_status"],
                "resource_status": state["resource_status"],
            })
        except sqlite3.Error:
            app.logger.exception("Database error while completing allocation.")
            return _allocation_error("ALLOCATION_UNAVAILABLE", "Unable to complete allocation.", 500)

    @app.route("/allocation/failure", methods=["POST"])
    @require_roles("ORGANIZATION")
    def fail_allocation():
        data, error = _allocation_json_body({"allocation_id", "reason"})
        if error:
            return error

        reason = data.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            return _allocation_error(
                "INVALID_REQUEST", "A non-empty failure reason is required.", 400
            )

        organization_id = g.resqtech_principal["organization_id"]
        try:
            result = get_allocation_coordinator(app).fail_allocation(
                data["allocation_id"], organization_id, reason.strip()
            )
            if not result.get("ok"):
                return _allocation_coordinator_error(result)

            state = _allocation_current_state(data["allocation_id"], organization_id)
            if state is None:
                return _allocation_error("NOT_FOUND", "Allocation not found.", 404)

            return jsonify({
                "allocation_id": data["allocation_id"],
                "status": state["status"],
                "response_status": state["response_status"],
                "requirement_unit_status": state["requirement_unit_status"],
                "resource_status": state["resource_status"],
            })
        except sqlite3.Error:
            app.logger.exception("Database error while failing allocation.")
            return _allocation_error("ALLOCATION_UNAVAILABLE", "Unable to record allocation failure.", 500)

    return app
