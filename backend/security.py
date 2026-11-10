
import base64
import hashlib
import hmac
import secrets


PBKDF2_ITERATIONS = 600_000
SALT_BYTES = 16
DIGEST_BYTES = 32
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 128


def validate_password(password: str) -> None:
    """Validate password type and length."""
    if not isinstance(password, str):
        raise TypeError("Password must be a string.")

    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        raise ValueError(
            f"Password must contain between "
            f"{PASSWORD_MIN_LENGTH} and {PASSWORD_MAX_LENGTH} characters."
        )


def hash_password(password: str) -> str:
    """Generate a salted PBKDF2-HMAC-SHA256 password hash."""
    validate_password(password)

    salt = secrets.token_bytes(SALT_BYTES)

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
        dklen=DIGEST_BYTES,
    )

    salt_encoded = base64.b64encode(salt).decode("ascii")
    digest_encoded = base64.b64encode(digest).decode("ascii")

    return (
        f"pbkdf2_sha256${PBKDF2_ITERATIONS}"
        f"${salt_encoded}${digest_encoded}"
    )


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored PBKDF2 hash."""
    if not isinstance(password, str) or not isinstance(stored_hash, str):
        return False
    if not PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH:
        return False

    if len(stored_hash) > 256:
        return False

    try:
        algorithm, iterations_text, salt_encoded, digest_encoded = (
            stored_hash.split("$")
        )

        if algorithm != "pbkdf2_sha256":
            return False

        iterations = int(iterations_text)

        # Reject malformed or unexpectedly expensive stored parameters.
        if iterations != PBKDF2_ITERATIONS:
            return False

        salt = base64.b64decode(salt_encoded, validate=True)
        expected_digest = base64.b64decode(
            digest_encoded,
            validate=True,
        )

        if len(salt) != SALT_BYTES:
            return False

        if len(expected_digest) != DIGEST_BYTES:
            return False

        actual_digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
            dklen=DIGEST_BYTES,
        )

        return hmac.compare_digest(actual_digest, expected_digest)

    except (ValueError, TypeError, UnicodeError):
        return False
