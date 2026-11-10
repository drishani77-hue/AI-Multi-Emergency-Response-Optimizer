
from getpass import getpass

from backend.config import ConfigurationError, load_admin_config
from backend.security import hash_password, validate_password


def powershell_assignment(name: str, value: str) -> str:
    """Format a value safely as a PowerShell single-quoted string."""
    escaped_value = value.replace("'", "''")
    return f"$env:{name} = '{escaped_value}'"


def main() -> None:
    print("ResQTech Admin Bootstrap")
    print("------------------------")
    print("Credentials are processed locally and are not saved to a file.\n")

    admin_id = input("Admin ID: ").strip()
    email = input("Admin email: ").strip()

    password = getpass("Admin password (hidden): ")
    confirmation = getpass("Confirm password (hidden): ")

    if password != confirmation:
        print("\nError: Passwords do not match.")
        return

    try:
        validate_password(password)

        password_hash = hash_password(password)

        config = load_admin_config(
            {
                "RESQTECH_ADMIN_ID": admin_id,
                "RESQTECH_ADMIN_EMAIL": email,
                "RESQTECH_ADMIN_PASSWORD_HASH": password_hash,
            }
        )

    except (ValueError, TypeError, ConfigurationError) as exc:
        print(f"\nConfiguration error: {exc}")
        return

    print("\nAdmin configuration generated successfully.")
    print("Copy these assignments into your PowerShell terminal:\n")

    print(powershell_assignment("RESQTECH_ADMIN_ID", config.admin_id))
    print(powershell_assignment("RESQTECH_ADMIN_EMAIL", config.email))
    print(
        powershell_assignment(
            "RESQTECH_ADMIN_PASSWORD_HASH",
            password_hash,
        )
    )

    print(
        "\nThese variables apply only to the current PowerShell session. "
        "Do not share the generated password hash."
    )


if __name__ == "__main__":
    main()
