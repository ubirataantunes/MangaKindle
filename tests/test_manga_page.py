from unittest.mock import AsyncMock, MagicMock

import main
from suwayomi_client import Chapter
from tests.conftest import read_csrf_token


def make_manga(chapter_ids: list[int]) -> MagicMock:
    chapters = [
        Chapter(id=chapter_id, name=f"Capítulo {chapter_id}", chapter_number=float(chapter_id), scanlator=None, source_order=0)
        for chapter_id in chapter_ids
    ]
    return MagicMock(
        id=7, title="Berserk", author=None, description=None, thumbnail_url=None, source_name="MangaDex", chapters=chapters
    )


def send(client, chapter_ids: list[int]):
    token = read_csrf_token(client, "/manga/7")
    return client.post(
        "/manga/7/enviar", data={"csrf_token": token, "capitulos": chapter_ids}, follow_redirects=False
    )


def test_queued_chapters_are_marked_and_cannot_be_selected(logged_client, fake_suwayomi):
    fake_suwayomi.get_manga_details = AsyncMock(return_value=make_manga([1, 2, 3]))
    main.database.create_job(7, "Berserk", "MangaDex", [2])

    page = logged_client.get("/manga/7").text

    assert "1 na fila" in page
    assert 'value="2" id="capitulo-2"\n             disabled' in page
    assert 'value="1" id="capitulo-1"\n             >' in page


def test_sending_again_does_not_queue_chapters_already_in_the_queue(logged_client, fake_suwayomi):
    fake_suwayomi.get_manga_details = AsyncMock(return_value=make_manga([1, 2, 3]))

    send(logged_client, [1, 2])
    send(logged_client, [1, 2, 3])

    jobs = sorted(main.database.recent_jobs(), key=lambda job: job.id)
    assert [job.chapter_ids for job in jobs] == [[1, 2], [3]]


def test_double_click_with_same_chapters_creates_a_single_job(logged_client, fake_suwayomi):
    fake_suwayomi.get_manga_details = AsyncMock(return_value=make_manga([1, 2]))

    send(logged_client, [1, 2])
    response = send(logged_client, [1, 2])

    assert len(main.database.recent_jobs()) == 1
    assert response.headers["location"] == "/manga/7"


def test_sent_chapters_are_not_queued_again(logged_client, fake_suwayomi):
    fake_suwayomi.get_manga_details = AsyncMock(return_value=make_manga([1, 2]))
    old_job = main.database.create_job(7, "Berserk", "MangaDex", [1])
    main.database.record_sent_chapters(old_job, manga_id=7, chapter_ids=[1])
    main.database.mark_job_sent(old_job)

    send(logged_client, [1, 2])

    newest_job = max(main.database.recent_jobs(), key=lambda job: job.id)
    assert newest_job.chapter_ids == [2]


def send_with_resend(client, chapter_ids: list[int]):
    token = read_csrf_token(client, "/manga/7")
    return client.post(
        "/manga/7/enviar",
        data={"csrf_token": token, "capitulos": chapter_ids, "reenviar": "true"},
        follow_redirects=False,
    )


def test_resend_queues_chapters_that_were_already_sent(logged_client, fake_suwayomi):
    fake_suwayomi.get_manga_details = AsyncMock(return_value=make_manga([1, 2]))
    old_job = main.database.create_job(7, "Berserk", "MangaDex", [1, 2])
    main.database.record_sent_chapters(old_job, manga_id=7, chapter_ids=[1, 2])
    main.database.mark_job_sent(old_job)

    send_with_resend(logged_client, [1, 2])

    newest_job = max(main.database.recent_jobs(), key=lambda job: job.id)
    assert newest_job.chapter_ids == [1, 2]
    assert newest_job.is_resend


def test_resend_still_skips_chapters_in_the_queue(logged_client, fake_suwayomi):
    fake_suwayomi.get_manga_details = AsyncMock(return_value=make_manga([1, 2]))
    main.database.create_job(7, "Berserk", "MangaDex", [1])

    send_with_resend(logged_client, [1, 2])

    newest_job = max(main.database.recent_jobs(), key=lambda job: job.id)
    assert newest_job.chapter_ids == [2]


def test_resend_option_appears_only_when_there_are_sent_chapters(logged_client, fake_suwayomi):
    fake_suwayomi.get_manga_details = AsyncMock(return_value=make_manga([1]))
    assert 'id="permitir-reenvio"' not in logged_client.get("/manga/7").text

    job_id = main.database.create_job(7, "Berserk", "MangaDex", [1])
    main.database.record_sent_chapters(job_id, manga_id=7, chapter_ids=[1])
    main.database.mark_job_sent(job_id)

    assert 'id="permitir-reenvio"' in logged_client.get("/manga/7").text
