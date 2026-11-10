
import base64

import pytest

from backend.security import (
    hash_password,
    verify_password,
    validate_password,
    PBKDF2_ITERATIONS,
    SALT_BYTES,
    DIGEST_BYTES,
)


def test_password_hash_format_and_parameters():
    stored = hash_password("SecureProjectPassword123!")

    parts = stored.split("$")

    assert len(parts) == 4
    assert parts[0] == "pbkdf2_sha256"
    assert int(parts[1]) == PBKDF2_ITERATIONS
    assert len(base64.b64decode(parts[2])) == SALT_BYTES
    assert len(base64.b64decode(parts[3])) == DIGEST_BYTES


def test_password_verification():
    password = "SecureProjectPassword123!"
    stored = hash_password(password)

    assert verify_password(password, stored)
    assert not verify_password("DifferentPassword123!", stored)


def test_each_password_gets_a_unique_salt():
    password = "SecureProjectPassword123!"

    first = hash_password(password)
    second = hash_password(password)

    assert first != second
    assert first.split("$")[2] != second.split("$")[2]


@pytest.mark.parametrize(
    "password",
    [
        "",
        "short",
        "12345678901",
        "a" * 129,
    ],
)
def test_invalid_password_lengths(password):
    with pytest.raises(ValueError):
        validate_password(password)


def test_non_string_password_rejected():
    with pytest.raises(TypeError):
        validate_password(None)


def test_malformed_hash_rejected():
    assert not verify_password(
        "SecureProjectPassword123!",
        "not-a-valid-hash",
    )


def test_oversized_hash_rejected():
    assert not verify_password(
        "SecureProjectPassword123!",
        "x" * 257,
    )


def test_wrong_iteration_count_rejected():
    assert not verify_password(
        "SecureProjectPassword123!",
        "pbkdf2_sha256$1$YWJj$YWJj",
    )


def test_short_password_rejected_during_verification():
    assert not verify_password(
        "short",
        "pbkdf2_sha256$600000$YWJj$YWJj",
    )
