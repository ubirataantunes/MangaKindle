import hmac
import ipaddress
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import Request
from fastapi.responses import RedirectResponse

SESSION_ID_KEY = "sessao_id"
CSRF_TOKEN_KEY = "csrf_token"
CSRF_FORM_FIELD = "csrf_token"
CLOUDFLARE_IP_HEADER = "CF-Connecting-IP"

password_hasher = PasswordHasher()


class LoginRequired(Exception):
    """Lançada quando uma página protegida é acessada sem login."""


class CsrfTokenInvalid(Exception):
    """Lançada quando o formulário não traz o token CSRF da sessão."""


def is_correct_password(typed_password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, typed_password)
    except (VerificationError, InvalidHashError):
        return False


def client_ip(request: Request, trusted_proxy_ips: frozenset[str]) -> str:
    peer_ip = request.client.host if request.client else "desconhecido"
    if peer_ip not in trusted_proxy_ips:
        return peer_ip

    forwarded_ip = request.headers.get(CLOUDFLARE_IP_HEADER, "").strip()
    try:
        return str(ipaddress.ip_address(forwarded_ip))
    except ValueError:
        return peer_ip


def csrf_token(request: Request) -> str:
    if CSRF_TOKEN_KEY not in request.session:
        request.session[CSRF_TOKEN_KEY] = secrets.token_urlsafe(32)
    return request.session[CSRF_TOKEN_KEY]


def is_login_enabled(request: Request) -> bool:
    return request.app.state.login_enabled


def is_logged_in(request: Request) -> bool:
    """Com o login desligado (só no uso local), todo acesso conta como logado."""
    if not is_login_enabled(request):
        return True

    session_id = request.session.get(SESSION_ID_KEY)
    if not session_id:
        return False
    return request.app.state.login_security.is_session_active(session_id)


def require_login(request: Request) -> None:
    if not is_logged_in(request):
        raise LoginRequired()


async def require_csrf_token(request: Request) -> None:
    session_token = request.session.get(CSRF_TOKEN_KEY, "")
    form = await request.form()
    submitted_token = form.get(CSRF_FORM_FIELD)

    if not session_token or not isinstance(submitted_token, str):
        raise CsrfTokenInvalid()
    if not hmac.compare_digest(submitted_token.encode(), session_token.encode()):
        raise CsrfTokenInvalid()


def redirect_to_login(request: Request, error: LoginRequired) -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)
