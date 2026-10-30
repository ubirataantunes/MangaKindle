import os
import re
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from argon2 import PasswordHasher

TEST_PASSWORD = "senha-de-teste-123"

# As variáveis precisam existir antes de importar main: ele carrega as configurações ao ser importado.
# Nunca lemos o .env real nem usamos a pasta data/ do projeto.
_IMPORT_DATA_DIRECTORY = Path(tempfile.mkdtemp(prefix="mangakindle-testes-"))
os.environ.update(
    {
        "APP_PASSWORD_HASH": PasswordHasher().hash(TEST_PASSWORD),
        "SESSION_SECRET": "segredo-de-sessao-ficticio",
        "SMTP_USERNAME": "remetente@example.com",
        "SMTP_PASSWORD": "senha-smtp-ficticia",
        "KINDLE_EMAIL": "kindle@example.com",
        "DATA_DIRECTORY": str(_IMPORT_DATA_DIRECTORY),
        "SECURE_COOKIES": "false",
        "TRUSTED_PROXY_IPS": "",
    }
)
os.environ.pop("APP_PASSWORD", None)

import pytest
from fastapi.testclient import TestClient

import main
from history_database import HistoryDatabase
from login_security_database import LoginSecurityDatabase

CSRF_FIELD_PATTERN = re.compile(r'name="csrf_token"\s+value="([^"]+)"')


def read_csrf_token(client: TestClient, path: str = "/login") -> str:
    """Abre uma página com formulário e devolve o token CSRF que ela mostra."""
    response = client.get(path)
    match = CSRF_FIELD_PATTERN.search(response.text)
    assert match, f"{path} não trouxe campo csrf_token (status {response.status_code})"
    return match.group(1)


def log_in(client: TestClient, password: str = TEST_PASSWORD):
    token = read_csrf_token(client)
    return client.post("/login", data={"senha": password, "csrf_token": token}, follow_redirects=False)


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Cada teste começa com bancos novos e sem trocar o estado dos outros."""
    login_security = LoginSecurityDatabase(tmp_path / "seguranca.sqlite")
    monkeypatch.setattr(main, "login_security", login_security)
    monkeypatch.setattr(main.app.state, "login_security", login_security)
    monkeypatch.setattr(main, "database", HistoryDatabase(tmp_path / "historico.sqlite"))
    return login_security


@pytest.fixture
def login_security(isolated_state) -> LoginSecurityDatabase:
    return isolated_state


@pytest.fixture
def fake_suwayomi(monkeypatch) -> MagicMock:
    """Substitui o cliente do Suwayomi; nenhum teste fala com a rede."""
    fake = MagicMock()
    fake.download_image = AsyncMock(return_value=(b"imagem", "image/png"))
    fake.list_installed_sources = AsyncMock(return_value=[])
    fake.search_manga = AsyncMock(return_value=([], False))
    fake.list_extension_store_urls = AsyncMock(return_value=[])
    fake.list_extensions = AsyncMock(return_value=[])
    fake.add_extension_store = AsyncMock()
    fake.remove_extension_store = AsyncMock()
    fake.refresh_extensions = AsyncMock()
    fake.install_extension = AsyncMock()
    fake.update_extension = AsyncMock()
    fake.uninstall_extension = AsyncMock()
    fake.get_manga_details = AsyncMock(
        return_value=MagicMock(id=1, title="Berserk", source_name="MangaDex", chapters=[])
    )
    monkeypatch.setattr(main, "suwayomi", fake)
    return fake


@pytest.fixture
def client(fake_suwayomi) -> TestClient:
    # Sem "with": não dispara o lifespan, que iniciaria o worker de envio.
    return TestClient(main.app_with_security_headers)


@pytest.fixture
def logged_client(client) -> TestClient:
    response = log_in(client)
    assert response.status_code == 303
    return client
