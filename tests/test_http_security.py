from fastapi.routing import APIRoute
from starlette.routing import Mount

import main
from tests.conftest import read_csrf_token

SECURITY_HEADERS = {
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
}


def post_routes() -> list[APIRoute]:
    return [route for route in main.app.routes if isinstance(route, APIRoute) and "POST" in route.methods]


def example_path(route_path: str) -> str:
    return route_path.replace("{manga_id}", "1").replace("{job_id}", "1").replace("{package_name}", "pacote.exemplo")


def assert_security_headers(response):
    headers = {name.lower(): value for name, value in response.headers.items()}
    for name, expected in SECURITY_HEADERS.items():
        assert headers.get(name) == expected, name
    assert "permissions-policy" in headers
    assert "camera=()" in headers["permissions-policy"]
    policy = headers["content-security-policy"]
    assert "frame-ancestors 'none'" in policy
    assert "default-src 'self'" in policy
    assert "unsafe-inline" not in policy
    assert "unsafe-eval" not in policy


# ---------- documentação desligada ----------

def test_docs_are_disabled(client):
    for docs_path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(docs_path, follow_redirects=False).status_code == 404, docs_path


def test_docs_are_disabled_even_when_logged_in(logged_client):
    for docs_path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
        assert logged_client.get(docs_path, follow_redirects=False).status_code == 404, docs_path


# ---------- headers de segurança ----------

def test_headers_on_a_page(client):
    assert_security_headers(client.get("/login"))


def test_headers_on_a_redirect(client):
    response = client.get("/buscar", follow_redirects=False)

    assert response.status_code == 303
    assert_security_headers(response)


def test_headers_on_an_error_page(logged_client):
    response = logged_client.get("/manga/0")

    assert response.status_code == 422
    assert_security_headers(response)


def test_headers_on_csrf_rejection(client):
    response = client.post("/login", data={"senha": "x"})

    assert response.status_code == 403
    assert_security_headers(response)


def test_headers_on_not_found(client):
    response = client.get("/rota-que-nao-existe")

    assert response.status_code == 404
    assert_security_headers(response)


def test_headers_on_static_files(client):
    response = client.get("/static/estilo.css")

    assert response.status_code == 200
    assert_security_headers(response)


def test_static_files_are_public(client):
    assert client.get("/static/manga.js", follow_redirects=False).status_code == 200


def test_static_files_do_not_expose_python_code(client):
    assert client.get("/static/../main.py", follow_redirects=False).status_code in (400, 404)


# ---------- toda rota protegida ----------

def test_every_route_except_login_and_static_redirects_to_login_without_session(client):
    checked = []
    for route in main.app.routes:
        if isinstance(route, Mount) or not isinstance(route, APIRoute):
            continue
        if route.path == "/login":
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            response = client.request(method, example_path(route.path), follow_redirects=False)
            assert response.status_code == 303, f"{method} {route.path} -> {response.status_code}"
            assert response.headers["location"] == "/login", f"{method} {route.path}"
            checked.append((method, route.path))

    assert ("GET", "/imagem") in checked
    assert ("POST", "/logout") in checked
    assert len(checked) >= 15


def test_protected_post_routes_without_session_do_not_run_the_action(client, fake_suwayomi):
    for route in post_routes():
        if route.path == "/login":
            continue
        client.post(example_path(route.path), data={"url": "https://x.com/a.json"}, follow_redirects=False)

    fake_suwayomi.add_extension_store.assert_not_called()
    fake_suwayomi.install_extension.assert_not_called()
    fake_suwayomi.uninstall_extension.assert_not_called()


# ---------- CSRF ----------

def test_there_are_post_routes_to_check():
    paths = {route.path for route in post_routes()}

    assert {"/login", "/logout", "/sessoes/encerrar-todas", "/extensoes/repositorios"} <= paths
    assert "/manga/{manga_id}/enviar" in paths
    assert "/envios/{job_id}/tentar-novamente" in paths


def test_every_post_route_rejects_missing_csrf_token_with_403(logged_client):
    for route in post_routes():
        response = logged_client.post(example_path(route.path), data={"senha": "x"}, follow_redirects=False)
        assert response.status_code == 403, f"{route.path} -> {response.status_code}"


def test_every_post_route_rejects_invalid_csrf_token_with_403(logged_client):
    for route in post_routes():
        response = logged_client.post(
            example_path(route.path), data={"csrf_token": "token-forjado"}, follow_redirects=False
        )
        assert response.status_code == 403, f"{route.path} -> {response.status_code}"


def test_login_rejects_missing_and_invalid_csrf_token(client):
    read_csrf_token(client)

    assert client.post("/login", data={"senha": "x"}).status_code == 403
    assert client.post("/login", data={"senha": "x", "csrf_token": "forjado"}).status_code == 403


def test_login_without_a_session_token_is_rejected(client):
    # Sem abrir a página antes, a sessão não tem token para comparar.
    assert client.post("/login", data={"senha": "x", "csrf_token": "qualquer"}).status_code == 403


def test_csrf_rejection_does_not_count_as_a_failed_login(client, login_security):
    for _ in range(10):
        client.post("/login", data={"senha": "x", "csrf_token": "forjado"})

    assert not login_security.is_login_blocked("testclient")


def test_csrf_rejection_shows_the_expired_form_message(client):
    response = client.post("/login", data={"senha": "x"})

    assert "Formulário expirado" in response.text


def test_token_from_another_session_is_rejected(logged_client, fake_suwayomi):
    from fastapi.testclient import TestClient

    other = TestClient(main.app_with_security_headers)
    foreign_token = read_csrf_token(other)

    response = logged_client.post("/extensoes/atualizar-lista", data={"csrf_token": foreign_token})

    assert response.status_code == 403
    fake_suwayomi.refresh_extensions.assert_not_called()


def test_valid_csrf_token_allows_the_action(logged_client, fake_suwayomi):
    token = read_csrf_token(logged_client, "/extensoes")

    response = logged_client.post("/extensoes/atualizar-lista", data={"csrf_token": token}, follow_redirects=False)

    assert response.status_code == 303
    fake_suwayomi.refresh_extensions.assert_awaited_once()


def test_forms_render_the_csrf_field(logged_client):
    for page in ("/login", "/extensoes", "/envios", "/buscar"):
        assert 'name="csrf_token"' in logged_client.get(page).text, page


def test_logged_in_header_has_logout_and_end_all_sessions(logged_client):
    body = logged_client.get("/buscar").text

    assert "/logout" in body
    assert "/sessoes/encerrar-todas" in body


def test_login_page_has_no_session_buttons(client):
    body = client.get("/login").text

    assert "/sessoes/encerrar-todas" not in body


# ---------- /imagem ----------

TRAVERSAL_QUERIES = [
    "/api/v1/manga/1/../2/thumbnail",
    "/api/v1/../../etc/passwd",
    "/api/v1/manga/1/thumbnail/..",
    "/api/v1/%2e%2e/admin",
    "/api/v1/manga/%2e%2e/1/thumbnail",
    "/api/v1/%2e%2e%2f%2e%2e%2fadmin",
    "/api/v1/manga/1%2fthumbnail",
    "/api/v1/manga/1%00/thumbnail",
    "%2fapi%2fv1%2fmanga%2f1%2fthumbnail",
    "/api/v1\\manga\\1\\thumbnail",
    "/api/v1/manga/1\\..\\thumbnail",
    "//evil.example/api/v1/manga/1/thumbnail",
    "/api/v1//manga/1/thumbnail",
    "http://evil.example/api/v1/manga/1/thumbnail",
    "https://evil.example/x",
    "ftp://evil.example/x",
    "evil.example/api/v1/manga/1/thumbnail",
    "api/v1/manga/1/thumbnail",
    "/api/v1/manga/1/thumbnail?x=1",
    "/api/v1/manga/1/thumbnail#frag",
    "/api/v1/manga/1/thumbnail\n",
    "/api/v1/manga/1/thumbnail%0d%0aX-Injected: 1",
    "/api/v1/manga/0/thumbnail",
    "/api/v1/manga/-1/thumbnail",
    "/api/v1/manga/abc/thumbnail",
    "/api/v1/manga/1/thumbnail/extra",
    "/api/v1/manga/1",
    "/api/v1/settings/about",
    "/api/graphql",
    "/api/v1/extension/icon/",
    "/api/v1/extension/icon/../../settings",
    "/api/v1/extension/icon/a/b",
    "/",
    "",
]


def test_every_traversal_attempt_is_404_and_never_reaches_suwayomi(logged_client, fake_suwayomi):
    for attempt in TRAVERSAL_QUERIES:
        response = logged_client.get("/imagem", params={"caminho": attempt}, follow_redirects=False)
        assert response.status_code in (404, 422), f"{attempt!r} -> {response.status_code}"

    fake_suwayomi.download_image.assert_not_called()


def test_raw_percent_encoded_attempts_are_404_and_never_reach_suwayomi(logged_client, fake_suwayomi):
    raw_queries = [
        "caminho=/api/v1/%2e%2e/admin",
        "caminho=/api/v1/%2E%2E/admin",
        "caminho=/api/v1/%2e%2e%2f%2e%2e%2fadmin",
        "caminho=%2e%2e/api/v1/manga/1/thumbnail",
        "caminho=/api/v1/manga/1/..%2fthumbnail",
        "caminho=/api/v1/manga/1/thumbnail%3Fx%3D1",
        "caminho=/api/v1/manga/1%5Cthumbnail",
        "caminho=//evil.example/x",
        "caminho=%2F%2Fevil.example%2Fx",
        "caminho=http%3A%2F%2Fevil.example%2Fx",
    ]

    for query in raw_queries:
        response = logged_client.get(f"/imagem?{query}", follow_redirects=False)
        assert response.status_code == 404, f"{query} -> {response.status_code}"

    fake_suwayomi.download_image.assert_not_called()


def test_extra_query_parameters_are_rejected_without_calling_suwayomi(logged_client, fake_suwayomi):
    for query in (
        "caminho=/api/v1/manga/1/thumbnail&outro=1",
        "caminho=/api/v1/manga/1/thumbnail&caminho=/api/v1/manga/2/thumbnail",
        "caminho=/api/v1/manga/1/thumbnail&url=http://evil.example",
    ):
        response = logged_client.get(f"/imagem?{query}", follow_redirects=False)
        assert response.status_code == 404, query

    fake_suwayomi.download_image.assert_not_called()


def test_missing_path_parameter_does_not_call_suwayomi(logged_client, fake_suwayomi):
    response = logged_client.get("/imagem", follow_redirects=False)

    assert response.status_code in (404, 422)
    fake_suwayomi.download_image.assert_not_called()


def test_allowed_cover_pattern_calls_suwayomi(logged_client, fake_suwayomi):
    response = logged_client.get("/imagem", params={"caminho": "/api/v1/manga/42/thumbnail"})

    assert response.status_code == 200
    assert response.content == b"imagem"
    assert response.headers["content-type"].startswith("image/png")
    fake_suwayomi.download_image.assert_awaited_once_with("/api/v1/manga/42/thumbnail")


def test_allowed_extension_icon_pattern_calls_suwayomi(logged_client, fake_suwayomi):
    path = "/api/v1/extension/icon/tachiyomi-en.mangadex-v1.4.1.apk"

    response = logged_client.get("/imagem", params={"caminho": path})

    assert response.status_code == 200
    fake_suwayomi.download_image.assert_awaited_once_with(path)


def test_image_proxy_requires_login(client, fake_suwayomi):
    response = client.get("/imagem", params={"caminho": "/api/v1/manga/1/thumbnail"}, follow_redirects=False)

    assert response.status_code == 303
    fake_suwayomi.download_image.assert_not_called()
