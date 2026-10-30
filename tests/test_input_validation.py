import pytest

from input_validation import (
    MAX_CHAPTERS_PER_SEND,
    MAX_SEARCH_TEXT_LENGTH,
    MAX_STORE_URL_LENGTH,
    InvalidInput,
    is_allowed_image_path,
    validate_chapter_ids,
    validate_extension_store_url,
    validate_package_name,
    validate_source_id,
)
from tests.conftest import read_csrf_token


# ---------- funções ----------

@pytest.mark.parametrize(
    "url",
    [
        "https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json",
        "https://raw.githubusercontent.com/FelipeGFA/extensoes/refs/heads/repo/index.pb",
    ],
)
def test_valid_store_url_is_returned_trimmed(url):
    assert validate_extension_store_url(f"  {url}  ") == url


@pytest.mark.parametrize(
    "url",
    [
        "http://exemplo.com/index.json",
        "ftp://exemplo.com/index.json",
        "javascript:alert(1)//.json",
        "file:///etc/passwd.json",
        "//exemplo.com/index.json",
        "exemplo.com/index.json",
        "https://exemplo.com/index.html",
        "https://exemplo.com/",
        "https://exemplo.com",
        "https:///index.json",
        "https://usuario:senha@exemplo.com/index.json",
        "https://usuario@exemplo.com/index.json",
        "",
        "   ",
        "https://exemplo.com/" + "a" * MAX_STORE_URL_LENGTH + ".json",
    ],
)
def test_invalid_store_url_is_rejected(url):
    with pytest.raises(InvalidInput):
        validate_extension_store_url(url)


def test_store_url_with_json_query_only_is_rejected():
    with pytest.raises(InvalidInput):
        validate_extension_store_url("https://exemplo.com/lista?arquivo=index.json")


def test_chapter_limit_is_200():
    assert MAX_CHAPTERS_PER_SEND == 200
    assert validate_chapter_ids(list(range(1, 201))) == list(range(1, 201))
    with pytest.raises(InvalidInput):
        validate_chapter_ids(list(range(1, 202)))


@pytest.mark.parametrize("chapter_ids", [[0], [-1], [5, 0, 7], [-10, 3]])
def test_non_positive_chapter_ids_are_rejected(chapter_ids):
    with pytest.raises(InvalidInput):
        validate_chapter_ids(chapter_ids)


@pytest.mark.parametrize("package_name", ["eu.kanade.tachiyomi.extension.en.mangadex", "pacote_1.2"])
def test_valid_package_name(package_name):
    assert validate_package_name(package_name) == package_name


@pytest.mark.parametrize("package_name", ["", "a b", "../x", "a/b", "pacote;rm", "a" * 201, "pacote%2e"])
def test_invalid_package_name(package_name):
    with pytest.raises(InvalidInput):
        validate_package_name(package_name)


@pytest.mark.parametrize("source_id", ["", "123", "9" * 20])
def test_valid_source_id(source_id):
    assert validate_source_id(source_id) == source_id


@pytest.mark.parametrize("source_id", ["abc", "-1", "1.5", "1 2", "9" * 21, "1; DROP TABLE"])
def test_invalid_source_id(source_id):
    with pytest.raises(InvalidInput):
        validate_source_id(source_id)


def test_image_path_function_matches_the_contract():
    assert is_allowed_image_path("/api/v1/manga/7/thumbnail")
    assert is_allowed_image_path("/api/v1/extension/icon/pacote.apk")
    assert not is_allowed_image_path("/api/v1/manga/7/../thumbnail")
    assert not is_allowed_image_path("/api/v1/manga/0/thumbnail")
    assert not is_allowed_image_path("http://exemplo.com/api/v1/manga/7/thumbnail")


# ---------- rotas ----------

def test_http_repository_url_is_rejected_with_400(logged_client, fake_suwayomi):
    token = read_csrf_token(logged_client, "/extensoes")

    response = logged_client.post(
        "/extensoes/repositorios",
        data={"url": "http://exemplo.com/index.json", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert "Dados inválidos" in response.text
    fake_suwayomi.add_extension_store.assert_not_called()


def test_repository_url_without_json_is_rejected(logged_client, fake_suwayomi):
    token = read_csrf_token(logged_client, "/extensoes")

    response = logged_client.post(
        "/extensoes/repositorios",
        data={"url": "https://exemplo.com/index.html", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 400
    fake_suwayomi.add_extension_store.assert_not_called()


def test_valid_repository_url_is_added(logged_client, fake_suwayomi):
    token = read_csrf_token(logged_client, "/extensoes")

    response = logged_client.post(
        "/extensoes/repositorios",
        data={"url": "https://exemplo.com/index.json", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303
    fake_suwayomi.add_extension_store.assert_awaited_once_with("https://exemplo.com/index.json")


def test_invalid_package_name_is_rejected_by_install_route(logged_client, fake_suwayomi):
    token = read_csrf_token(logged_client, "/extensoes")

    response = logged_client.post(
        "/extensoes/pacote;ruim/instalar", data={"csrf_token": token}, follow_redirects=False
    )

    assert response.status_code == 400
    fake_suwayomi.install_extension.assert_not_called()


def test_more_than_200_chapters_is_rejected(logged_client, fake_suwayomi):
    token = read_csrf_token(logged_client, "/extensoes")

    response = logged_client.post(
        "/manga/1/enviar",
        data={"csrf_token": token, "capitulos": [str(number) for number in range(1, 202)]},
        follow_redirects=False,
    )

    assert response.status_code == 400
    fake_suwayomi.get_manga_details.assert_not_called()


def test_exactly_200_chapters_is_accepted(logged_client, fake_suwayomi):
    token = read_csrf_token(logged_client, "/extensoes")

    response = logged_client.post(
        "/manga/1/enviar",
        data={"csrf_token": token, "capitulos": [str(number) for number in range(1, 201)]},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/envios"


@pytest.mark.parametrize("chapter_id", ["0", "-5"])
def test_non_positive_chapter_ids_are_rejected_by_the_route(logged_client, fake_suwayomi, chapter_id):
    token = read_csrf_token(logged_client, "/extensoes")

    response = logged_client.post(
        "/manga/1/enviar", data={"csrf_token": token, "capitulos": [chapter_id]}, follow_redirects=False
    )

    assert response.status_code == 400
    fake_suwayomi.get_manga_details.assert_not_called()


def test_search_text_longer_than_limit_is_rejected(logged_client, fake_suwayomi):
    response = logged_client.get("/buscar", params={"fonte": "1", "texto": "a" * (MAX_SEARCH_TEXT_LENGTH + 1)})

    assert response.status_code == 422
    fake_suwayomi.search_manga.assert_not_called()


def test_search_text_at_limit_is_accepted(logged_client, fake_suwayomi):
    response = logged_client.get("/buscar", params={"fonte": "1", "texto": "a" * MAX_SEARCH_TEXT_LENGTH})

    assert response.status_code == 200
    fake_suwayomi.search_manga.assert_awaited_once()


@pytest.mark.parametrize("page", ["0", "-1", "1001", "abc"])
def test_invalid_page_number_is_rejected(logged_client, fake_suwayomi, page):
    response = logged_client.get("/buscar", params={"fonte": "1", "pagina": page})

    assert response.status_code == 422
    fake_suwayomi.search_manga.assert_not_called()


def test_invalid_source_id_is_rejected_by_search(logged_client, fake_suwayomi):
    response = logged_client.get("/buscar", params={"fonte": "abc"})

    assert response.status_code == 400
    fake_suwayomi.search_manga.assert_not_called()


def test_long_extension_filter_is_rejected(logged_client):
    assert logged_client.get("/extensoes", params={"filtro": "a" * 101}).status_code == 422


@pytest.mark.parametrize("manga_id", ["0", "-1", "abc"])
def test_manga_id_must_be_a_positive_integer(logged_client, fake_suwayomi, manga_id):
    response = logged_client.get(f"/manga/{manga_id}")

    assert response.status_code == 422
    fake_suwayomi.get_manga_details.assert_not_called()


@pytest.mark.parametrize("job_id", ["0", "-1", "abc"])
def test_job_id_must_be_a_positive_integer(logged_client, job_id):
    token = read_csrf_token(logged_client, "/envios")

    response = logged_client.post(
        f"/envios/{job_id}/tentar-novamente", data={"csrf_token": token}, follow_redirects=False
    )

    assert response.status_code == 422


def test_validation_error_page_does_not_echo_the_input(logged_client):
    response = logged_client.get("/buscar", params={"fonte": "1", "texto": "<script>x</script>" * 20})

    assert "<script>x</script>" not in response.text
