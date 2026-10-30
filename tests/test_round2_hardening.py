import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import main
from login import is_correct_password
from password_hash import MIN_PASSWORD_LENGTH, generate_password_hash
from suwayomi_client import SuwayomiError
from tests.conftest import TEST_PASSWORD
from tests.test_http_security import assert_security_headers

PROJECT_ROOT = Path(__file__).parent.parent
APP_DIRECTORY = PROJECT_ROOT / "app"
INTERNAL_URL = "http://suwayomi:4567/api/graphql"


# ---------- (a) proxy headers do uvicorn desligados ----------

def uvicorn_command() -> list[str]:
    dockerfile = (APP_DIRECTORY / "Dockerfile").read_text(encoding="utf-8")
    match = re.search(r"^CMD\s+(\[.*\])\s*$", dockerfile, re.MULTILINE)
    assert match, "Dockerfile sem CMD em formato JSON"
    return re.findall(r'"([^"]*)"', match.group(1))


def test_dockerfile_disables_uvicorn_proxy_headers():
    command = uvicorn_command()

    assert "--no-proxy-headers" in command
    assert "--proxy-headers" not in command
    assert "--forwarded-allow-ips" not in command


def test_dockerfile_serves_the_app_wrapped_with_security_headers():
    assert "main:app_with_security_headers" in uvicorn_command()


def test_forwarded_allow_ips_is_gone_from_compose_files_and_env_example():
    for file_name in ("docker-compose.yml", "docker-compose.prod.yml", ".env.example"):
        assert "FORWARDED_ALLOW_IPS" not in (PROJECT_ROOT / file_name).read_text(encoding="utf-8"), file_name


def test_prod_compose_trusts_only_the_fixed_cloudflared_ip():
    compose = (PROJECT_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")

    assert "TRUSTED_PROXY_IPS" in compose


# ---------- (b) erro 500 não tratado ----------

@pytest.fixture
def exploding_route():
    async def explode():
        raise RuntimeError("detalhe-interno-secreto /app/main.py linha 42")

    main.app.add_api_route("/_teste-explode", explode, methods=["GET"])
    yield "/_teste-explode"
    main.app.router.routes[:] = [
        route for route in main.app.router.routes if getattr(route, "path", None) != "/_teste-explode"
    ]


def test_unhandled_error_is_500_with_security_headers_and_no_traceback(fake_suwayomi, exploding_route):
    client = TestClient(main.app_with_security_headers, raise_server_exceptions=False)

    response = client.get(exploding_route)

    assert response.status_code == 500
    assert_security_headers(response)
    assert "Traceback" not in response.text
    assert "detalhe-interno-secreto" not in response.text
    assert "RuntimeError" not in response.text
    assert "main.py" not in response.text


def test_fastapi_app_is_still_the_plain_fastapi_object():
    from fastapi import FastAPI

    assert isinstance(main.app, FastAPI)
    assert main.app_with_security_headers is not main.app


# ---------- (c) gerador de hash ----------

@pytest.mark.parametrize("password", ["", "1234567", "curta"])
def test_short_passwords_are_refused(password):
    assert len(password) < MIN_PASSWORD_LENGTH

    with pytest.raises(ValueError):
        generate_password_hash(password)


def test_minimum_length_is_eight():
    assert MIN_PASSWORD_LENGTH == 8
    assert generate_password_hash("12345678").startswith("$argon2")


def test_generated_hash_is_argon2_and_verifiable():
    password_hash = generate_password_hash(TEST_PASSWORD)

    assert password_hash.startswith("$argon2")
    assert TEST_PASSWORD not in password_hash
    assert is_correct_password(TEST_PASSWORD, password_hash)
    assert not is_correct_password("outra-senha-qualquer", password_hash)


def test_command_prints_error_and_no_hash_for_a_short_password(monkeypatch, capsys):
    import password_hash

    answers = iter(["curta", "curta"])
    monkeypatch.setattr(password_hash, "getpass", lambda prompt: next(answers))

    assert password_hash.main() == 1

    captured = capsys.readouterr()
    assert "$argon2" not in captured.out
    assert "8" in captured.err


def test_command_refuses_different_confirmation(monkeypatch, capsys):
    import password_hash

    answers = iter(["senha-longa-1", "senha-longa-2"])
    monkeypatch.setattr(password_hash, "getpass", lambda prompt: next(answers))

    assert password_hash.main() == 1
    assert "$argon2" not in capsys.readouterr().out


def test_command_prints_a_verifiable_hash(monkeypatch, capsys):
    import password_hash

    answers = iter([TEST_PASSWORD, TEST_PASSWORD])
    monkeypatch.setattr(password_hash, "getpass", lambda prompt: next(answers))

    assert password_hash.main() == 0

    printed = capsys.readouterr().out.strip()
    assert is_correct_password(TEST_PASSWORD, printed)


# ---------- (d) mensagem genérica nos erros do Suwayomi ----------

@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError(f"Falha ao conectar em {INTERNAL_URL}"),
        httpx.ReadTimeout(f"timeout em {INTERNAL_URL}"),
        SuwayomiError(f"Resposta ruim de {INTERNAL_URL}"),
    ],
)
def test_suwayomi_errors_show_a_generic_message_without_internal_details(logged_client, fake_suwayomi, error):
    fake_suwayomi.list_installed_sources.side_effect = error

    response = logged_client.get("/buscar")

    assert response.status_code == 502
    assert "O Suwayomi não respondeu como esperado. Tente de novo em instantes." in response.text
    assert "suwayomi:4567" not in response.text
    assert INTERNAL_URL not in response.text
    assert error.__class__.__name__ not in response.text


def test_suwayomi_error_detail_goes_only_to_the_log(logged_client, fake_suwayomi, caplog):
    fake_suwayomi.list_installed_sources.side_effect = httpx.ConnectError(f"Falha em {INTERNAL_URL}")

    with caplog.at_level("WARNING"):
        logged_client.get("/buscar")

    assert INTERNAL_URL in caplog.text


def test_suwayomi_error_page_keeps_security_headers(logged_client, fake_suwayomi):
    fake_suwayomi.list_installed_sources.side_effect = httpx.ConnectError(INTERNAL_URL)

    assert_security_headers(logged_client.get("/buscar"))


# ---------- (e) ícone de fonte: padrão removido ----------

@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/source/123/icon",
        "/api/v1/source/9223372036854775807/icon",
        "/api/v1/source/abc/icon",
    ],
)
def test_source_icon_pattern_is_refused_without_calling_suwayomi(logged_client, fake_suwayomi, path):
    response = logged_client.get("/imagem", params={"caminho": path}, follow_redirects=False)

    assert response.status_code == 404
    fake_suwayomi.download_image.assert_not_called()


def test_source_icon_uses_the_extension_icon_path_which_is_allowed(logged_client, fake_suwayomi):
    # No Suwayomi v2.4.2366 o iconUrl da fonte aponta para /api/v1/extension/icon/<pkgName>.
    path = "/api/v1/extension/icon/eu.kanade.tachiyomi.extension.en.mangadex"

    response = logged_client.get("/imagem", params={"caminho": path})

    assert response.status_code == 200
    fake_suwayomi.download_image.assert_awaited_once_with(path)
