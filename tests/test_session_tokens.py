
import re

import pytest

from backend.session_tokens import (
    TOKEN_BYTES,
    generate_token,
    hash_token,
    verify_token,
)


def test_generated_token_has_correct_format_and_length():
    token = generate_token()

    assert isinstance(token, str)
    assert len(token) == 43
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token)


def test_generated_token_decodes_to_32_bytes():
    import base64

    token = generate_token()
    decoded = base64.urlsafe_b64decode(token + "=")

    assert len(decoded) == TOKEN_BYTES


def test_each_generated_token_is_unique():
    first = generate_token()
    second = generate_token()

    assert first != second


def test_token_hash_is_sha256_hex():
    token = generate_token()
    stored_hash = hash_token(token)

    assert len(stored_hash) == 64
    assert re.fullmatch(r"[0-9a-f]{64}", stored_hash)


def test_raw_token_verifies_against_its_hash():
    token = generate_token()
    stored_hash = hash_token(token)

    assert verify_token(token, stored_hash)


def test_different_token_does_not_verify():
    first = generate_token()
    second = generate_token()

    assert not verify_token(first, hash_token(second))


@pytest.mark.parametrize(
    "token",
    [
        "",
        "invalid-token",
        "a" * 42,
        "a" * 44,
        "!" * 43,
    ],
)
def test_malformed_tokens_are_rejected(token):
    with pytest.raises(ValueError):
        hash_token(token)


def test_non_string_token_is_rejected():
    with pytest.raises(TypeError):
        hash_token(None)


@pytest.mark.parametrize(
    "stored_hash",
    [
        "",
        "invalid",
        "A" * 64,
        "g" * 64,
        "a" * 63,
    ],
)
def test_malformed_stored_hashes_do_not_verify(stored_hash):
    assert not verify_token(generate_token(), stored_hash)


def test_non_string_values_do_not_verify():
    assert not verify_token(None, "a" * 64)
    assert not verify_token(generate_token(), None)
