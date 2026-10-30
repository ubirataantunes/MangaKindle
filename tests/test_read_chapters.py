from unittest.mock import AsyncMock

import main
from tests.conftest import read_csrf_token
from tests.test_manga_page import make_manga


def mark(client, action: str, chapter_id: int):
    token = read_csrf_token(client, "/manga/7")
    return client.post(
        f"/manga/7/{action}", data={"csrf_token": token, "capitulo": chapter_id}, follow_redirects=False
    )


def test_marking_one_chapter_as_read_returns_to_that_chapter(logged_client, fake_suwayomi):
    fake_suwayomi.get_manga_details = AsyncMock(return_value=make_manga([1, 2, 3]))

    response = mark(logged_client, "lido", 2)

    assert response.status_code == 303
    assert response.headers["location"] == "/manga/7#capitulo-2"
    assert main.database.read_chapter_ids(7) == {2}


def test_read_up_to_here_marks_previous_chapters_too(logged_client, fake_suwayomi):
    fake_suwayomi.get_manga_details = AsyncMock(return_value=make_manga([1, 2, 3, 4]))

    mark(logged_client, "lido-ate-aqui", 3)

    assert main.database.read_chapter_ids(7) == {1, 2, 3}


def test_read_up_to_unknown_chapter_marks_nothing(logged_client, fake_suwayomi):
    fake_suwayomi.get_manga_details = AsyncMock(return_value=make_manga([1, 2]))

    mark(logged_client, "lido-ate-aqui", 99)

    assert main.database.read_chapter_ids(7) == set()


def test_unmarking_removes_only_that_chapter(logged_client, fake_suwayomi):
    fake_suwayomi.get_manga_details = AsyncMock(return_value=make_manga([1, 2]))
    main.database.mark_chapters_read(7, [1, 2])

    mark(logged_client, "nao-lido", 1)

    assert main.database.read_chapter_ids(7) == {2}


def test_manga_page_shows_read_chapters(logged_client, fake_suwayomi):
    fake_suwayomi.get_manga_details = AsyncMock(return_value=make_manga([1, 2, 3]))
    main.database.mark_chapters_read(7, [1])

    page = logged_client.get("/manga/7").text

    assert "1 lidos" in page
    assert 'formaction="/manga/7/nao-lido" name="capitulo" value="1"' in page
    assert 'formaction="/manga/7/lido" name="capitulo" value="2"' in page


def test_marking_as_read_requires_csrf_token(logged_client, fake_suwayomi):
    response = logged_client.post("/manga/7/lido", data={"capitulo": 1}, follow_redirects=False)

    assert response.status_code == 403
    assert main.database.read_chapter_ids(7) == set()
