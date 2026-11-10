
import os
from dataclasses import dataclass, field
from collections.abc import Mapping


class ConfigurationError(RuntimeError):
    """Raised when required application configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class AdminConfig:
    admin_id: str
    email: str
    password_hash: str = field(repr=False)
    can_override_severity: bool = False


def load_admin_config(
    environ: Mapping[str, str] | None = None,
) -> AdminConfig:
    """
    Load Admin configuration from environment variables.

    Required:
        RESQTECH_ADMIN_ID
        RESQTECH_ADMIN_EMAIL
        RESQTECH_ADMIN_PASSWORD_HASH

    Optional:
        RESQTECH_ADMIN_CAN_OVERRIDE_SEVERITY
        Only the exact value 'true' enables this permission.
    """

    source = os.environ if environ is None else environ

    required_variables = (
        "RESQTECH_ADMIN_ID",
        "RESQTECH_ADMIN_EMAIL",
        "RESQTECH_ADMIN_PASSWORD_HASH",
    )

    missing = [
        name
        for name in required_variables
        if not isinstance(source.get(name), str)
        or not source.get(name, "").strip()
    ]

    if missing:
        raise ConfigurationError(
            "Missing required Admin configuration: "
            + ", ".join(missing)
        )

    admin_id = source["RESQTECH_ADMIN_ID"].strip()
    email = source["RESQTECH_ADMIN_EMAIL"].strip().lower()
    password_hash = source["RESQTECH_ADMIN_PASSWORD_HASH"].strip()

    if not admin_id or not email or not password_hash:
        raise ConfigurationError("Admin configuration contains empty values.")

    if not email.isascii() or email.count("@") != 1:
        raise ConfigurationError("Admin email configuration is invalid.")

    local_part, domain = email.split("@")

    if (
        not local_part
        or not domain
        or domain.startswith(".")
        or domain.endswith(".")
        or "." not in domain
    ):
        raise ConfigurationError("Admin email configuration is invalid.")

    can_override = (
        source.get("RESQTECH_ADMIN_CAN_OVERRIDE_SEVERITY", "").strip()
        == "true"
    )

    return AdminConfig(
        admin_id=admin_id,
        email=email,
        password_hash=password_hash,
        can_override_severity=can_override,
    )
