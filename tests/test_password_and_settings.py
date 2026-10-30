import pytest
from argon2 import PasswordHasher

from login import is_correct_password
from settings import load_settings

REQUIRED_ENVIRONMENT = {
    "SESSION_SECRET": "segredo",
    "SMTP_USERNAME": "remetente@example.com",
    "SMTP_PASSWORD": "senha-smtp",
    "KINDLE_EMAIL": "kindle@example.com",
}


@pytest.fixture
def clean_environment(monkeypatch, tmp_path):
    for variable in ("APP_PASSWORD", "APP_PASSWORD_HASH", "SECURE_COOKIES", "TRUSTED_PROXY_IPS", "LOGIN_ENABLED"):
        monkeypatch.delenv(variable, raising=False)
    for variable, value in REQUIRED_ENVIRONMENT.items():
        monkeypatch.setenv(variable, value)
    monkeypatch.setenv("DATA_DIRECTORY", str(tmp_path))
    return monkeypatch


# ---------- argon2 ----------

def test_correct_password_is_accepted():
    password_hash = PasswordHasher().hash("minha-senha")

    assert is_correct_password("minha-senha", password_hash)


def test_wrong_password_is_rejected():
    password_hash = PasswordHasher().hash("minha-senha")

    assert not is_correct_password("outra-senha", password_hash)
    assert not is_correct_password("", password_hash)


def test_invalid_hash_returns_false_instead_of_raising():
    assert not is_correct_password("minha-senha", "isto-nao-e-um-hash")
    assert not is_correct_password("minha-senha", "")


def test_plain_text_password_is_not_accepted_as_a_hash():
    assert not is_correct_password("minha-senha", "minha-senha")


def test_hash_is_salted_and_argon2():
    first = PasswordHasher().hash("igual")
    second = PasswordHasher().hash("igual")

    assert first != second
    assert first.startswith("$argon2")


# ---------- load_settings ----------

def test_load_settings_requires_the_password_hash(clean_environment):
    with pytest.raises(RuntimeError, match="APP_PASSWORD_HASH"):
        load_settings()


def test_load_settings_rejects_the_old_plain_password(clean_environment):
    clean_environment.setenv("APP_PASSWORD", "senha-em-texto-puro")

    with pytest.raises(RuntimeError) as error:
        load_settings()

    assert "password_hash" in str(error.value)
    assert "senha-em-texto-puro" not in str(error.value)


def test_load_settings_reads_the_hash(clean_environment):
    clean_environment.setenv("APP_PASSWORD_HASH", "$argon2id$exemplo")

    assert load_settings().app_password_hash == "$argon2id$exemplo"


def test_secure_cookies_default_to_true(clean_environment):
    clean_environment.setenv("APP_PASSWORD_HASH", "hash")

    assert load_settings().secure_cookies is True


@pytest.mark.parametrize("value", ["false", "FALSE", "0", "no", "No"])
def test_secure_cookies_can_be_turned_off(clean_environment, value):
    clean_environment.setenv("APP_PASSWORD_HASH", "hash")
    clean_environment.setenv("SECURE_COOKIES", value)

    assert load_settings().secure_cookies is False


@pytest.mark.parametrize("value", ["true", "1", "yes", "qualquer-coisa", ""])
def test_secure_cookies_stay_on_for_any_other_value(clean_environment, value):
    clean_environment.setenv("APP_PASSWORD_HASH", "hash")
    clean_environment.setenv("SECURE_COOKIES", value)

    assert load_settings().secure_cookies is True


def test_trusted_proxy_ips_are_parsed(clean_environment):
    clean_environment.setenv("APP_PASSWORD_HASH", "hash")
    clean_environment.setenv("TRUSTED_PROXY_IPS", "172.30.0.2, 10.0.0.1 ,")

    assert load_settings().trusted_proxy_ips == frozenset({"172.30.0.2", "10.0.0.1"})


def test_trusted_proxy_ips_default_to_none(clean_environment):
    clean_environment.setenv("APP_PASSWORD_HASH", "hash")

    assert load_settings().trusted_proxy_ips == frozenset()


def test_required_secrets_are_still_required(clean_environment):
    clean_environment.setenv("APP_PASSWORD_HASH", "hash")
    clean_environment.delenv("SESSION_SECRET")

    with pytest.raises(RuntimeError, match="SESSION_SECRET"):
        load_settings()


# ---------- login desligado (uso local) ----------

def test_login_is_enabled_by_default(clean_environment):
    clean_environment.setenv("APP_PASSWORD_HASH", "$argon2id$exemplo")

    assert load_settings().login_enabled is True


def test_login_can_be_disabled_locally_without_password_hash(clean_environment):
    clean_environment.setenv("LOGIN_ENABLED", "false")
    clean_environment.setenv("SECURE_COOKIES", "false")

    settings = load_settings()

    assert settings.login_enabled is False
    assert settings.app_password_hash == ""


def test_login_cannot_be_disabled_with_secure_cookies(clean_environment):
    clean_environment.setenv("APP_PASSWORD_HASH", "$argon2id$exemplo")
    clean_environment.setenv("LOGIN_ENABLED", "false")
    clean_environment.setenv("SECURE_COOKIES", "true")

    with pytest.raises(RuntimeError, match="LOGIN_ENABLED"):
        load_settings()
