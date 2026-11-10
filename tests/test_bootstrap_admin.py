
import pytest

from backend.bootstrap_admin import main, powershell_assignment
from backend.security import verify_password


def test_powershell_assignment_escapes_apostrophes():
    result = powershell_assignment("TEST_VARIABLE", "it's-working")

    assert result == "$env:TEST_VARIABLE = 'it''s-working'"


def test_password_confirmation_mismatch_stops_bootstrap(
    monkeypatch,
    capsys,
):
    monkeypatch.setattr("builtins.input", lambda _: "admin001")

    passwords = iter(["FirstPassword123!", "DifferentPassword123!"])
    monkeypatch.setattr(
        "backend.bootstrap_admin.getpass",
        lambda _: next(passwords),
    )

    main()

    output = capsys.readouterr().out

    assert "Passwords do not match" in output
    assert "RESQTECH_ADMIN_PASSWORD_HASH" not in output


def test_invalid_email_stops_bootstrap(monkeypatch, capsys):
    answers = iter(["admin001", "invalid-email"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    passwords = iter(["SecurePassword123!", "SecurePassword123!"])
    monkeypatch.setattr(
        "backend.bootstrap_admin.getpass",
        lambda _: next(passwords),
    )

    main()

    output = capsys.readouterr().out

    assert "Configuration error" in output
    assert "RESQTECH_ADMIN_PASSWORD_HASH" not in output


def test_successful_bootstrap_prints_hash_not_plaintext(
    monkeypatch,
    capsys,
):
    plaintext_password = "SecurePassword123!"

    answers = iter(["admin001", "admin@example.com"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    passwords = iter([plaintext_password, plaintext_password])
    monkeypatch.setattr(
        "backend.bootstrap_admin.getpass",
        lambda _: next(passwords),
    )

    main()

    output = capsys.readouterr().out

    assert "generated successfully" in output
    assert plaintext_password not in output
    assert "$env:RESQTECH_ADMIN_ID = 'admin001'" in output
    assert "$env:RESQTECH_ADMIN_EMAIL = 'admin@example.com'" in output

    hash_line = next(
        line
        for line in output.splitlines()
        if line.startswith("$env:RESQTECH_ADMIN_PASSWORD_HASH = ")
    )

    password_hash = hash_line.split(" = ", 1)[1].strip("'")

    assert verify_password(plaintext_password, password_hash)
