import pytest

import main


@pytest.fixture
def login_disabled(monkeypatch):
    monkeypatch.setattr(main.app.state, "login_enabled", False)


def test_protected_pages_open_without_login(client, login_disabled):
    for path in ("/buscar", "/extensoes", "/envios"):
        assert client.get(path, follow_redirects=False).status_code == 200


def test_login_page_redirects_home(client, login_disabled):
    response = client.get("/login", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_logout_buttons_are_hidden(client, login_disabled):
    page = client.get("/envios").text

    assert 'action="/logout"' not in page
    assert 'action="/sessoes/encerrar-todas"' not in page


def test_forms_still_require_csrf_token(client, login_disabled):
    response = client.post("/envios/1/tentar-novamente", data={}, follow_redirects=False)

    assert response.status_code == 403


def test_pages_still_require_login_when_enabled(client):
    response = client.get("/buscar", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
