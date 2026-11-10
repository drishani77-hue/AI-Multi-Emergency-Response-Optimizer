
import pytest

from backend.config import (
    AdminConfig,
    ConfigurationError,
    load_admin_config,
)


VALID_ENV = {
    "RESQTECH_ADMIN_ID": "admin001",
    "RESQTECH_ADMIN_EMAIL": "ADMIN@example.com",
    "RESQTECH_ADMIN_PASSWORD_HASH": "test-password-hash",
}


def test_valid_admin_configuration():
    config = load_admin_config(VALID_ENV)

    assert isinstance(config, AdminConfig)
    assert config.admin_id == "admin001"
    assert config.email == "admin@example.com"


def test_severity_override_disabled_by_default():
    config = load_admin_config(VALID_ENV)

    assert config.can_override_severity is False


def test_severity_override_enabled_only_by_exact_true():
    environment = {
        **VALID_ENV,
        "RESQTECH_ADMIN_CAN_OVERRIDE_SEVERITY": "true",
    }

    assert load_admin_config(environment).can_override_severity is True


@pytest.mark.parametrize("value", ["TRUE", "True", "1", "yes", "false", ""])
def test_other_permission_values_do_not_enable_override(value):
    environment = {
        **VALID_ENV,
        "RESQTECH_ADMIN_CAN_OVERRIDE_SEVERITY": value,
    }

    assert load_admin_config(environment).can_override_severity is False


@pytest.mark.parametrize(
    "missing_variable",
    [
        "RESQTECH_ADMIN_ID",
        "RESQTECH_ADMIN_EMAIL",
        "RESQTECH_ADMIN_PASSWORD_HASH",
    ],
)
def test_missing_required_configuration_fails_closed(missing_variable):
    environment = {
        key: value
        for key, value in VALID_ENV.items()
        if key != missing_variable
    }

    with pytest.raises(ConfigurationError):
        load_admin_config(environment)


def test_invalid_email_rejected():
    environment = {
        **VALID_ENV,
        "RESQTECH_ADMIN_EMAIL": "invalid-email",
    }

    with pytest.raises(ConfigurationError):
        load_admin_config(environment)


def test_password_hash_hidden_from_repr():
    config = load_admin_config(VALID_ENV)

    assert "test-password-hash" not in repr(config)


def test_configuration_is_immutable():
    config = load_admin_config(VALID_ENV)

    with pytest.raises(AttributeError):
        config.admin_id = "another-admin"


def test_environment_mapping_is_not_modified():
    environment = VALID_ENV.copy()

    load_admin_config(environment)

    assert environment == VALID_ENV
