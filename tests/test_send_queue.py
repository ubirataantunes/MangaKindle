import asyncio
from pathlib import Path

import httpx
import pytest

import send_queue
from history_database import HistoryDatabase
from send_queue import SendJobError, SendQueueWorker
from settings import Settings
from suwayomi_client import Chapter, MangaDetails

ONE_MEGABYTE = 1024 * 1024


class FakeSuwayomi:
    def __init__(self, chapters: list[Chapter]):
        self._chapters = chapters

    async def get_manga_details(self, manga_id: int) -> MangaDetails:
        return MangaDetails(
            id=manga_id,
            title="Berserk",
            author=None,
            description=None,
            thumbnail_url=None,
            source_name="MangaDex",
            chapters=self._chapters,
        )

    async def get_chapter_page_urls(self, chapter_id: int) -> list[str]:
        return [f"/api/v1/capitulo/{chapter_id}/pagina/0", f"/api/v1/capitulo/{chapter_id}/pagina/1"]

    async def download_image(self, image_url: str) -> tuple[bytes, str]:
        return b"imagem", "image/jpeg"


class FakeKindle:
    """Substitui o KCC e o SMTP, guardando os títulos dos livros enviados."""

    def __init__(self, epub_size_by_chapter_count: dict[int, int]):
        self._epub_size_by_chapter_count = epub_size_by_chapter_count
        self.sent_titles: list[str] = []

    def convert_to_epub(self, pages_directory: Path, output_directory: Path, book_title, source_name, kindle_profile) -> Path:
        chapter_count = len(list(pages_directory.iterdir()))
        output_directory.mkdir(parents=True)
        book_path = output_directory / "livro.epub"
        book_path.write_bytes(b"x" * self._epub_size_by_chapter_count[chapter_count])
        return book_path

    def send_book_to_kindle(self, settings, book_path: Path, book_title: str) -> None:
        self.sent_titles.append(book_title)


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_password_hash="hash-de-teste",
        session_secret="segredo",
        suwayomi_url="http://suwayomi:4567",
        data_directory=tmp_path,
        smtp_host="smtp.exemplo.com",
        smtp_port=587,
        smtp_username="eu@exemplo.com",
        smtp_password="senha",
        sender_email="eu@exemplo.com",
        kindle_email="eu@kindle.com",
        kindle_profile="KPW5",
        max_attachment_megabytes=1,
        max_emails_per_day=3,
    )


def make_chapters(*chapter_numbers: float) -> list[Chapter]:
    # O Suwayomi devolve sourceOrder 0 para o capítulo mais recente.
    total = len(chapter_numbers)
    return [
        Chapter(id=int(number), name=f"Capítulo {number}", chapter_number=number, scanlator=None, source_order=total - index - 1)
        for index, number in enumerate(chapter_numbers)
    ]


@pytest.fixture
def database(tmp_path) -> HistoryDatabase:
    return HistoryDatabase(tmp_path / "historico.sqlite")


def run_next_job(tmp_path, database, chapters, fake_kindle, monkeypatch):
    monkeypatch.setattr(send_queue, "convert_to_epub", fake_kindle.convert_to_epub)
    monkeypatch.setattr(send_queue, "send_book_to_kindle", fake_kindle.send_book_to_kindle)
    worker = SendQueueWorker(make_settings(tmp_path), database, FakeSuwayomi(chapters))
    job = database.take_next_pending_job()
    asyncio.run(worker._process_job(job))


def test_chapters_already_sent_are_skipped(tmp_path, database, monkeypatch):
    chapters = make_chapters(1, 2, 3)
    first_job_id = database.create_job(7, "Berserk", "MangaDex", [1])
    database.record_sent_chapters(first_job_id, manga_id=7, chapter_ids=[1])
    database.create_job(7, "Berserk", "MangaDex", [1, 2, 3])
    database.take_next_pending_job()
    fake_kindle = FakeKindle(epub_size_by_chapter_count={2: 100})

    run_next_job(tmp_path, database, chapters, fake_kindle, monkeypatch)

    assert fake_kindle.sent_titles == ["[MangaDex] Berserk - Cap. 2-3"]
    assert database.sent_chapter_ids(7) == {1, 2, 3}


def test_chapters_listed_newest_first_are_sent_in_reading_order(tmp_path, database, monkeypatch):
    chapters = make_chapters(113, 112, 111, 110)
    database.create_job(7, "Berserk", "MangaDex", [110, 111, 112, 113])
    fake_kindle = FakeKindle(epub_size_by_chapter_count={4: 100})

    run_next_job(tmp_path, database, chapters, fake_kindle, monkeypatch)

    assert fake_kindle.sent_titles == ["[MangaDex] Berserk - Cap. 110-113"]


def test_bundle_is_split_when_epub_exceeds_attachment_limit(tmp_path, database, monkeypatch):
    chapters = make_chapters(1, 2, 3, 4)
    database.create_job(7, "Berserk", "MangaDex", [1, 2, 3, 4])
    fake_kindle = FakeKindle(epub_size_by_chapter_count={4: 2 * ONE_MEGABYTE, 2: 100})

    run_next_job(tmp_path, database, chapters, fake_kindle, monkeypatch)

    assert fake_kindle.sent_titles == ["[MangaDex] Berserk - Cap. 1-2", "[MangaDex] Berserk - Cap. 3-4"]


def test_single_chapter_too_big_fails_the_job(tmp_path, database, monkeypatch):
    chapters = make_chapters(1)
    database.create_job(7, "Berserk", "MangaDex", [1])
    fake_kindle = FakeKindle(epub_size_by_chapter_count={1: 2 * ONE_MEGABYTE})

    with pytest.raises(SendJobError):
        run_next_job(tmp_path, database, chapters, fake_kindle, monkeypatch)

    assert fake_kindle.sent_titles == []
    assert database.sent_chapter_ids(7) == set()


def test_work_directory_is_removed_after_sending(tmp_path, database, monkeypatch):
    chapters = make_chapters(1)
    job_id = database.create_job(7, "Berserk", "MangaDex", [1])
    fake_kindle = FakeKindle(epub_size_by_chapter_count={1: 100})

    run_next_job(tmp_path, database, chapters, fake_kindle, monkeypatch)

    assert not (tmp_path / "work" / f"envio_{job_id}").exists()


class FlakySuwayomi(FakeSuwayomi):
    """Cada página falha algumas vezes antes de funcionar, e registra quantas baixam ao mesmo tempo."""

    def __init__(self, chapters: list[Chapter], failures_per_page: int, pages_per_chapter: int = 2):
        super().__init__(chapters)
        self._failures_left_by_url: dict[str, int] = {}
        self._failures_per_page = failures_per_page
        self._pages_per_chapter = pages_per_chapter
        self.downloads_in_progress = 0
        self.most_downloads_at_once = 0

    async def get_chapter_page_urls(self, chapter_id: int) -> list[str]:
        return [f"/api/v1/capitulo/{chapter_id}/pagina/{page}" for page in range(self._pages_per_chapter)]

    async def download_image(self, image_url: str) -> tuple[bytes, str]:
        self.downloads_in_progress += 1
        self.most_downloads_at_once = max(self.most_downloads_at_once, self.downloads_in_progress)
        try:
            await asyncio.sleep(0.01)
            failures_left = self._failures_left_by_url.setdefault(image_url, self._failures_per_page)
            if failures_left > 0:
                self._failures_left_by_url[image_url] = failures_left - 1
                raise httpx.ConnectError("fonte instável")
            return b"imagem", "image/jpeg"
        finally:
            self.downloads_in_progress -= 1


class ProgressRecorder(HistoryDatabase):
    def __init__(self, database_path: Path):
        super().__init__(database_path)
        self.progress_messages: list[str] = []

    def update_job_progress(self, job_id: int, progress: str) -> None:
        self.progress_messages.append(progress)
        super().update_job_progress(job_id, progress)


def run_job_with(tmp_path, database, suwayomi, fake_kindle, monkeypatch):
    monkeypatch.setattr(send_queue, "convert_to_epub", fake_kindle.convert_to_epub)
    monkeypatch.setattr(send_queue, "send_book_to_kindle", fake_kindle.send_book_to_kindle)
    monkeypatch.setattr(send_queue, "SECONDS_BEFORE_PAGE_RETRY", 0)
    worker = SendQueueWorker(make_settings(tmp_path), database, suwayomi)
    asyncio.run(worker._process_job(database.take_next_pending_job()))


def test_pages_are_downloaded_in_parallel_up_to_the_limit(tmp_path, database, monkeypatch):
    database.create_job(7, "Berserk", "MangaDex", [1])
    suwayomi = FlakySuwayomi(make_chapters(1), failures_per_page=0, pages_per_chapter=20)

    run_job_with(tmp_path, database, suwayomi, FakeKindle({1: 100}), monkeypatch)

    assert suwayomi.most_downloads_at_once == send_queue.PAGES_DOWNLOADED_IN_PARALLEL


def test_page_that_fails_temporarily_is_retried(tmp_path, database, monkeypatch):
    database.create_job(7, "Berserk", "MangaDex", [1])
    suwayomi = FlakySuwayomi(make_chapters(1), failures_per_page=send_queue.PAGE_DOWNLOAD_ATTEMPTS - 1)
    fake_kindle = FakeKindle({1: 100})

    run_job_with(tmp_path, database, suwayomi, fake_kindle, monkeypatch)

    assert fake_kindle.sent_titles == ["[MangaDex] Berserk - Cap. 1"]


def test_page_that_keeps_failing_fails_the_job_with_clear_message(tmp_path, database, monkeypatch):
    database.create_job(7, "Berserk", "MangaDex", [1])
    suwayomi = FlakySuwayomi(make_chapters(1), failures_per_page=send_queue.PAGE_DOWNLOAD_ATTEMPTS)

    with pytest.raises(SendJobError, match="Não deu para baixar uma página do capítulo Capítulo 1"):
        run_job_with(tmp_path, database, suwayomi, FakeKindle({1: 100}), monkeypatch)


def test_progress_is_reported_at_each_step(tmp_path, monkeypatch):
    database = ProgressRecorder(tmp_path / "historico.sqlite")
    database.create_job(7, "Berserk", "MangaDex", [1, 2, 3, 4])
    fake_kindle = FakeKindle(epub_size_by_chapter_count={4: 2 * ONE_MEGABYTE, 2: 100})

    run_job_with(tmp_path, database, FakeSuwayomi(make_chapters(1, 2, 3, 4)), fake_kindle, monkeypatch)

    assert database.progress_messages == [
        "Buscando a lista de capítulos",
        "Baixando capítulo 1 de 4 (Capítulo 1)",
        "Baixando capítulo 2 de 4 (Capítulo 2)",
        "Baixando capítulo 3 de 4 (Capítulo 3)",
        "Baixando capítulo 4 de 4 (Capítulo 4)",
        "Convertendo Cap. 1-4 · 0 de 4 capítulos enviados",
        "Convertendo Cap. 1-2 · 0 de 4 capítulos enviados",
        "Enviando Cap. 1-2 por e-mail · 0 de 4 capítulos enviados",
        "Convertendo Cap. 3-4 · 2 de 4 capítulos enviados",
        "Enviando Cap. 3-4 por e-mail · 2 de 4 capítulos enviados",
    ]


def test_resend_job_sends_chapters_already_sent_before(tmp_path, database, monkeypatch):
    first_job = database.create_job(7, "Berserk", "MangaDex", [1, 2])
    database.record_sent_chapters(first_job, manga_id=7, chapter_ids=[1, 2])
    database.take_next_pending_job()
    database.mark_job_sent(first_job)
    database.create_job(7, "Berserk", "MangaDex", [1, 2], is_resend=True)
    fake_kindle = FakeKindle(epub_size_by_chapter_count={2: 100})

    run_next_job(tmp_path, database, make_chapters(1, 2), fake_kindle, monkeypatch)

    assert fake_kindle.sent_titles == ["[MangaDex] Berserk - Cap. 1-2"]


def test_retried_resend_skips_what_this_resend_already_delivered(tmp_path, database, monkeypatch):
    first_job = database.create_job(7, "Berserk", "MangaDex", [1, 2])
    database.record_sent_chapters(first_job, manga_id=7, chapter_ids=[1, 2])
    database.take_next_pending_job()
    database.mark_job_sent(first_job)
    resend_job = database.create_job(7, "Berserk", "MangaDex", [1, 2], is_resend=True)
    # Este reenvio já tinha mandado o capítulo 1 antes de falhar.
    database.record_sent_chapters(resend_job, manga_id=7, chapter_ids=[1])
    fake_kindle = FakeKindle(epub_size_by_chapter_count={1: 100})

    run_next_job(tmp_path, database, make_chapters(1, 2), fake_kindle, monkeypatch)

    assert fake_kindle.sent_titles == ["[MangaDex] Berserk - Cap. 2"]


def test_each_email_is_counted(tmp_path, database, monkeypatch):
    chapters = make_chapters(1, 2, 3, 4)
    database.create_job(7, "Berserk", "MangaDex", [1, 2, 3, 4])
    fake_kindle = FakeKindle(epub_size_by_chapter_count={4: 2 * ONE_MEGABYTE, 2: 100})

    run_next_job(tmp_path, database, chapters, fake_kindle, monkeypatch)

    assert len(database.email_times_in_last_day()) == 2


def test_job_stops_at_daily_email_limit_and_keeps_what_was_sent(tmp_path, database, monkeypatch):
    for _ in range(2):
        database.record_sent_email(job_id=99, book_title="Outro livro")
    chapters = make_chapters(1, 2, 3, 4)
    database.create_job(7, "Berserk", "MangaDex", [1, 2, 3, 4])
    fake_kindle = FakeKindle(epub_size_by_chapter_count={4: 2 * ONE_MEGABYTE, 2: 100})

    with pytest.raises(SendJobError, match="Limite de 3 e-mails"):
        run_next_job(tmp_path, database, chapters, fake_kindle, monkeypatch)

    assert fake_kindle.sent_titles == ["[MangaDex] Berserk - Cap. 1-2"]
    assert database.sent_chapter_ids(7) == {1, 2}
