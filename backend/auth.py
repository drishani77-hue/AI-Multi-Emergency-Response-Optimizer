
from functools import wraps

from flask import current_app, g, jsonify, request

from backend.app import SESSION_COOKIE
from backend.sessions import (
    get_active_session,
    verify_session_csrf,
)


STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def require_authentication(view):
    """Require a valid session and CSRF protection for state changes."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        session_token = request.cookies.get(SESSION_COOKIE)

        if not session_token:
            return jsonify({
                "error": "UNAUTHENTICATED",
                "message": "Authentication is required.",
            }), 401

        db_path = current_app.config["DATABASE_PATH"]

        active_session = get_active_session(
            session_token,
            db_path,
        )

        if active_session is None:
            return jsonify({
                "error": "UNAUTHENTICATED",
                "message": "Authentication is required.",
            }), 401

        if request.method in STATE_CHANGING_METHODS:
            csrf_token = request.headers.get("X-CSRF-Token")

            if not csrf_token or not verify_session_csrf(
                session_token,
                csrf_token,
                db_path,
            ):
                return jsonify({
                    "error": "INVALID_CSRF_TOKEN",
                    "message": "CSRF verification failed.",
                }), 403

        principal_type = active_session["principal_type"]
        principal_id = active_session["principal_id"]

        g.resqtech_session = active_session

        g.resqtech_principal = {
            "type": principal_type,
            "id": principal_id,
            "organization_id": active_session["organization_id"],
        }

        return view(*args, **kwargs)

    return wrapped


def require_roles(*allowed_roles):
    """Require authentication and one of the specified principal roles."""

    valid_roles = {"ORGANIZATION", "ADMIN"}

    if not allowed_roles or any(
        role not in valid_roles for role in allowed_roles
    ):
        raise ValueError("At least one valid role must be specified.")

    def decorator(view):
        @wraps(view)
        @require_authentication
        def wrapped(*args, **kwargs):
            principal = g.resqtech_principal

            if principal["type"] not in allowed_roles:
                return jsonify({
                    "error": "FORBIDDEN",
                    "message": "You do not have permission to access this resource.",
                }), 403

            return view(*args, **kwargs)

        return wrapped

    return decorator
