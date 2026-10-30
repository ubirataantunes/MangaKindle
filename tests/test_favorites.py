from unittest.mock import AsyncMock, MagicMock

import main
from tests.conftest import read_csrf_token


def make_manga_details(manga_id: int = 1) -> MagicMock:
    return MagicMock(
        id=manga_id,
        title="Berserk",
        author=None,
        description=None,
        thumbnail_url=f"/api/v1/manga/{manga_id}/thumbnail",
        source_name="MangaDex",
        chapters=[],
    )


def test_favorite_button_adds_manga_to_favorites_page(logged_client, fake_suwayomi):
    fake_suwayomi.get_manga_details = AsyncMock(return_value=make_manga_details())
    token = read_csrf_token(logged_client, "/manga/1")

    response = logged_client.post("/manga/1/favoritar", data={"csrf_token": token}, follow_redirects=False)

    assert response.status_code == 303
    assert main.database.is_favorite(1)
    favorites_page = logged_client.get("/favoritos").text
    assert "Berserk" in favorites_page
    assert 'href="/manga/1"' in favorites_page


def test_manga_page_shows_remove_option_when_favorite(logged_client, fake_suwayomi):
    fake_suwayomi.get_manga_details = AsyncMock(return_value=make_manga_details())
    main.database.add_favorite(1, "Berserk", "MangaDex", None)

    page = logged_client.get("/manga/1").text

    assert 'action="/manga/1/desfavoritar"' in page


def test_unfavorite_removes_manga(logged_client, fake_suwayomi):
    fake_suwayomi.get_manga_details = AsyncMock(return_value=make_manga_details())
    main.database.add_favorite(1, "Berserk", "MangaDex", None)
    token = read_csrf_token(logged_client, "/manga/1")

    logged_client.post("/manga/1/desfavoritar", data={"csrf_token": token}, follow_redirects=False)

    assert not main.database.is_favorite(1)


def test_favoriting_requires_csrf_token(logged_client, fake_suwayomi):
    response = logged_client.post("/manga/1/favoritar", data={}, follow_redirects=False)

    assert response.status_code == 403
    assert not main.database.is_favorite(1)


def test_favorites_page_requires_login(client):
    response = client.get("/favoritos", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
