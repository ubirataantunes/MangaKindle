import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_password_hash: str
    session_secret: str
    suwayomi_url: str
    data_directory: Path
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    sender_email: str
    kindle_email: str
    kindle_profile: str
    max_attachment_megabytes: int
    secure_cookies: bool = True
    trusted_proxy_ips: frozenset[str] = frozenset()
    login_enabled: bool = True
    # O Gmail bloqueia o envio por um dia inteiro ao passar de 500 e-mails em 24 horas.
    max_emails_per_day: int = 500


def _required(variable_name: str) -> str:
    value = os.environ.get(variable_name, "").strip()
    if not value:
        raise RuntimeError(f"A variável de ambiente {variable_name} é obrigatória.")
    return value


def _password_hash(login_enabled: bool) -> str:
    password_hash = os.environ.get("APP_PASSWORD_HASH", "").strip()
    if password_hash or not login_enabled:
        return password_hash

    if os.environ.get("APP_PASSWORD", "").strip():
        raise RuntimeError(
            "APP_PASSWORD não é mais aceita. Gere o hash com 'python password_hash.py' "
            "e defina APP_PASSWORD_HASH (veja o README)."
        )
    raise RuntimeError(
        "Com LOGIN_ENABLED=true, a variável APP_PASSWORD_HASH é obrigatória. "
        "Gere com 'python password_hash.py' (veja \"Ligar a senha\" no README) ou use LOGIN_ENABLED=false."
    )


def _secure_cookies() -> bool:
    value = os.environ.get("SECURE_COOKIES", "true").strip().lower()
    return value not in ("false", "0", "no")


def _login_enabled(secure_cookies: bool) -> bool:
    value = os.environ.get("LOGIN_ENABLED", "true").strip().lower()
    login_enabled = value not in ("false", "0", "no")

    # Cookies seguros só fazem sentido com HTTPS, ou seja, fora do computador local.
    # Lá o app nunca pode ficar sem senha, mesmo que alguém esqueça LOGIN_ENABLED=false no .env.
    if not login_enabled and secure_cookies:
        raise RuntimeError(
            "LOGIN_ENABLED=false só é permitido no uso local (com SECURE_COOKIES=false). "
            "Em produção o login é obrigatório."
        )
    return login_enabled


def _trusted_proxy_ips() -> frozenset[str]:
    raw_value = os.environ.get("TRUSTED_PROXY_IPS", "")
    return frozenset(address.strip() for address in raw_value.split(",") if address.strip())


def load_settings() -> Settings:
    smtp_username = _required("SMTP_USERNAME")
    secure_cookies = _secure_cookies()
    login_enabled = _login_enabled(secure_cookies)

    return Settings(
        app_password_hash=_password_hash(login_enabled),
        session_secret=_required("SESSION_SECRET"),
        suwayomi_url=os.environ.get("SUWAYOMI_URL", "http://suwayomi:4567").rstrip("/"),
        data_directory=Path(os.environ.get("DATA_DIRECTORY", "/data")),
        smtp_host=os.environ.get("SMTP_HOST", "smtp.gmail.com"),
        smtp_port=int(os.environ.get("SMTP_PORT", "587")),
        smtp_username=smtp_username,
        smtp_password=_required("SMTP_PASSWORD"),
        sender_email=os.environ.get("SENDER_EMAIL", smtp_username),
        kindle_email=_required("KINDLE_EMAIL"),
        kindle_profile=os.environ.get("KINDLE_PROFILE", "KPW5"),
        # O Gmail recusa anexos acima de 25 MB; a margem cobre o aumento do base64 no e-mail.
        max_attachment_megabytes=int(os.environ.get("MAX_ATTACHMENT_MEGABYTES", "17")),
        max_emails_per_day=int(os.environ.get("MAX_EMAILS_PER_DAY", "500")),
        secure_cookies=secure_cookies,
        trusted_proxy_ips=_trusted_proxy_ips(),
        login_enabled=login_enabled,
    )
