
import base64
import hashlib
import hmac
import re
import secrets


TOKEN_BYTES = 32
TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")
HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")


def generate_token() -> str:
    """Generate a cryptographically secure 32-byte URL-safe token."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def _validate_token(token: str) -> None:
    """Validate the format and decoded length of a generated token."""
    if not isinstance(token, str):
        raise TypeError("Token must be a string.")

    if not TOKEN_PATTERN.fullmatch(token):
        raise ValueError("Token format is invalid.")

    try:
        decoded = base64.urlsafe_b64decode(token + "=")
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError("Token encoding is invalid.") from exc

    if len(decoded) != TOKEN_BYTES:
        raise ValueError("Token must contain exactly 32 decoded bytes.")

    canonical = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")

    if canonical != token:
        raise ValueError("Token encoding is not canonical.")


def hash_token(token: str) -> str:
    """Return the lowercase SHA-256 hexadecimal digest of a token."""
    _validate_token(token)

    return hashlib.sha256(token.encode("ascii")).hexdigest()


def verify_token(token: str, stored_hash: str) -> bool:
    """Verify a raw token against its stored SHA-256 hash."""
    if not isinstance(token, str) or not isinstance(stored_hash, str):
        return False

    if not HASH_PATTERN.fullmatch(stored_hash):
        return False

    try:
        actual_hash = hash_token(token)
    except (TypeError, ValueError):
        return False

    return hmac.compare_digest(actual_hash, stored_hash)
