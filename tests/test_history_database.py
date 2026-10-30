from history_database import STATUS_ERROR, STATUS_PENDING, STATUS_PROCESSING, STATUS_SENT, HistoryDatabase


def create_database(tmp_path) -> HistoryDatabase:
    return HistoryDatabase(tmp_path / "historico.sqlite")


def test_new_job_is_taken_from_queue_as_processing(tmp_path):
    database = create_database(tmp_path)
    job_id = database.create_job(7, "Berserk", "MangaDex", [1, 2])

    job = database.take_next_pending_job()

    assert job.id == job_id
    assert job.chapter_ids == [1, 2]
    assert job.status == STATUS_PROCESSING
    assert database.take_next_pending_job() is None


def test_sent_chapters_are_remembered_per_manga(tmp_path):
    database = create_database(tmp_path)
    job_id = database.create_job(7, "Berserk", "MangaDex", [1, 2])

    database.record_sent_chapters(job_id, manga_id=7, chapter_ids=[1, 2])

    assert database.sent_chapter_ids(7) == {1, 2}
    assert database.sent_chapter_ids(8) == set()


def test_only_failed_jobs_can_be_retried(tmp_path):
    database = create_database(tmp_path)
    failed_job_id = database.create_job(7, "Berserk", "MangaDex", [1])
    sent_job_id = database.create_job(7, "Berserk", "MangaDex", [2])
    database.mark_job_failed(failed_job_id, "SMTP fora do ar")
    database.mark_job_sent(sent_job_id)

    database.retry_job(failed_job_id)
    database.retry_job(sent_job_id)

    status_by_job = {job.id: job.status for job in database.recent_jobs()}
    assert status_by_job[failed_job_id] == STATUS_PENDING
    assert status_by_job[sent_job_id] == STATUS_SENT


def test_failed_job_keeps_error_message(tmp_path):
    database = create_database(tmp_path)
    job_id = database.create_job(7, "Berserk", "MangaDex", [1])

    database.mark_job_failed(job_id, "SMTP fora do ar")

    job = database.recent_jobs()[0]
    assert job.status == STATUS_ERROR
    assert job.error_message == "SMTP fora do ar"


def test_interrupted_jobs_go_back_to_queue(tmp_path):
    database = create_database(tmp_path)
    job_id = database.create_job(7, "Berserk", "MangaDex", [1])
    database.take_next_pending_job()

    database.requeue_interrupted_jobs()

    assert database.take_next_pending_job().id == job_id


def test_favorite_is_added_listed_and_removed(tmp_path):
    database = create_database(tmp_path)

    database.add_favorite(7, "Berserk", "MangaDex", "/api/v1/manga/7/thumbnail")

    assert database.is_favorite(7)
    favorites = database.favorite_mangas()
    assert [favorite.title for favorite in favorites] == ["Berserk"]
    assert favorites[0].source_name == "MangaDex"

    database.remove_favorite(7)

    assert not database.is_favorite(7)
    assert database.favorite_mangas() == []


def test_favoriting_again_updates_data_and_keeps_original_date(tmp_path):
    database = create_database(tmp_path)
    database.add_favorite(7, "Berserk", "MangaDex", None)
    original_date = database.favorite_mangas()[0].added_at

    database.add_favorite(7, "Berserk (Deluxe)", "MangaDex", "/api/v1/manga/7/thumbnail")

    favorites = database.favorite_mangas()
    assert len(favorites) == 1
    assert favorites[0].title == "Berserk (Deluxe)"
    assert favorites[0].added_at == original_date


def test_favorites_are_listed_in_alphabetical_order(tmp_path):
    database = create_database(tmp_path)
    database.add_favorite(1, "vagabond", "MangaDex", None)
    database.add_favorite(2, "Berserk", "MangaDex", None)
    database.add_favorite(3, "akira", "MangaDex", None)

    assert [favorite.title for favorite in database.favorite_mangas()] == ["akira", "Berserk", "vagabond"]


def test_progress_is_shown_while_processing_and_cleared_when_finished(tmp_path):
    database = create_database(tmp_path)
    job_id = database.create_job(7, "Berserk", "MangaDex", [1])
    database.take_next_pending_job()

    database.update_job_progress(job_id, "Baixando capítulo 1 de 1")
    assert database.recent_jobs()[0].progress == "Baixando capítulo 1 de 1"

    database.mark_job_sent(job_id)
    assert database.recent_jobs()[0].progress is None


def test_old_database_without_progress_column_is_upgraded(tmp_path):
    import sqlite3

    # Nome próprio: o conftest já cria um historico.sqlite novo nesta mesma pasta.
    database_path = tmp_path / "historico_antigo.sqlite"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE send_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, manga_id INTEGER NOT NULL, manga_title TEXT NOT NULL,
                source_name TEXT NOT NULL, chapter_ids TEXT NOT NULL, status TEXT NOT NULL,
                error_message TEXT, created_at TEXT NOT NULL, finished_at TEXT
            )
            """
        )
        connection.execute(
            "INSERT INTO send_jobs (manga_id, manga_title, source_name, chapter_ids, status, created_at) "
            "VALUES (7, 'Berserk', 'MangaDex', '[1]', 'pendente', '2026-10-29T20:00:00')"
        )

    database = HistoryDatabase(database_path)

    job = database.recent_jobs()[0]
    assert job.manga_title == "Berserk"
    assert job.progress is None


def test_queued_chapters_are_those_in_unfinished_jobs(tmp_path):
    database = create_database(tmp_path)
    pending_job = database.create_job(7, "Berserk", "MangaDex", [1, 2])
    processing_job = database.create_job(7, "Berserk", "MangaDex", [3])
    sent_job = database.create_job(7, "Berserk", "MangaDex", [4])
    failed_job = database.create_job(7, "Berserk", "MangaDex", [5])
    database.create_job(8, "Vagabond", "MangaDex", [9])
    database.take_next_pending_job()  # o primeiro vira "processando"
    database.take_next_pending_job()
    database.mark_job_sent(sent_job)
    database.mark_job_failed(failed_job, "erro")

    assert database.queued_chapter_ids(7) == {1, 2, 3}


def test_emails_older_than_one_day_do_not_count(tmp_path):
    database = create_database(tmp_path)
    with database._connect() as connection:
        connection.execute(
            "INSERT INTO sent_emails (job_id, book_title, sent_at) VALUES (1, 'Antigo', '2000-01-01T10:00:00')"
        )
    database.record_sent_email(job_id=2, book_title="Novo")

    assert len(database.email_times_in_last_day()) == 1


def test_marking_read_twice_keeps_one_entry(tmp_path):
    database = create_database(tmp_path)
    database.mark_chapters_read(7, [1, 2])
    database.mark_chapters_read(7, [2, 3])

    assert database.read_chapter_ids(7) == {1, 2, 3}
    assert database.read_chapter_ids(8) == set()
