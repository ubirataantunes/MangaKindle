import asyncio
import logging
import shutil
from collections import deque
from datetime import timedelta
from pathlib import Path

import httpx

from chapter_bundling import DownloadedChapter, group_chapters_by_size, split_bundle_in_half
from history_database import HistoryDatabase, SendJob
from kindle_conversion import build_book_title, convert_to_epub, format_chapter_range
from kindle_email import send_book_to_kindle
from settings import Settings
from suwayomi_client import Chapter, SuwayomiClient

logger = logging.getLogger(__name__)

SECONDS_BETWEEN_QUEUE_CHECKS = 3

# Baixar uma página por vez deixava capítulos longos muito lentos. Mais que isso costuma
# esbarrar no limite de requisições das fontes.
PAGES_DOWNLOADED_IN_PARALLEL = 6
PAGE_DOWNLOAD_ATTEMPTS = 3
SECONDS_BEFORE_PAGE_RETRY = 2

IMAGE_EXTENSION_BY_CONTENT_TYPE = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


class SendJobError(Exception):
    pass


class SendQueueWorker:
    def __init__(self, settings: Settings, database: HistoryDatabase, suwayomi: SuwayomiClient):
        self._settings = settings
        self._database = database
        self._suwayomi = suwayomi
        self._max_attachment_bytes = settings.max_attachment_megabytes * 1024 * 1024

    async def run_forever(self) -> None:
        self._database.requeue_interrupted_jobs()

        while True:
            job = self._database.take_next_pending_job()
            if job is None:
                await asyncio.sleep(SECONDS_BETWEEN_QUEUE_CHECKS)
                continue

            try:
                await self._process_job(job)
                self._database.mark_job_sent(job.id)
            except Exception as error:
                logger.exception("Falha no envio %s", job.id)
                self._database.mark_job_failed(job.id, str(error) or error.__class__.__name__)

    async def _process_job(self, job: SendJob) -> None:
        self._database.update_job_progress(job.id, "Buscando a lista de capítulos")
        manga = await self._suwayomi.get_manga_details(job.manga_id)

        # Num envio normal, capítulos que já chegaram ao Kindle são pulados. Num reenvio pedido
        # pelo usuário eles vão de novo; só pulamos os que este mesmo reenvio já mandou,
        # para o "Tentar de novo" não duplicar nada.
        if job.is_resend:
            already_sent_ids = self._database.chapter_ids_sent_by_job(job.id)
        else:
            already_sent_ids = self._database.sent_chapter_ids(job.manga_id)

        chapters_to_send = [
            chapter
            for chapter in manga.chapters
            if chapter.id in job.chapter_ids and chapter.id not in already_sent_ids
        ]
        if not chapters_to_send:
            return

        # Algumas fontes listam do mais novo pro mais antigo; cada livro precisa abrir no menor capítulo.
        chapters_to_send.sort(key=lambda chapter: chapter.chapter_number)

        work_directory = self._settings.data_directory / "work" / f"envio_{job.id}"
        shutil.rmtree(work_directory, ignore_errors=True)

        try:
            downloaded_chapters = await self._download_chapters(job, chapters_to_send, work_directory / "capitulos")
            await self._convert_and_send_bundles(job, manga.title, manga.source_name, downloaded_chapters, work_directory)
        finally:
            shutil.rmtree(work_directory, ignore_errors=True)

    async def _download_chapters(
        self, job: SendJob, chapters: list[Chapter], chapters_directory: Path
    ) -> list[DownloadedChapter]:
        downloaded_chapters = []

        for position, chapter in enumerate(chapters):
            self._database.update_job_progress(
                job.id, f"Baixando capítulo {position + 1} de {len(chapters)} ({chapter.name})"
            )
            chapter_directory = chapters_directory / f"{position:04d}"
            downloaded_chapters.append(await self._download_chapter(chapter, chapter_directory))

        return downloaded_chapters

    async def _download_chapter(self, chapter: Chapter, chapter_directory: Path) -> DownloadedChapter:
        page_urls = await self._suwayomi.get_chapter_page_urls(chapter.id)
        if not page_urls:
            raise SendJobError(f"O capítulo {chapter.name} não tem páginas.")

        chapter_directory.mkdir(parents=True, exist_ok=True)
        free_download_slots = asyncio.Semaphore(PAGES_DOWNLOADED_IN_PARALLEL)

        async def download_page(page_index: int, page_url: str) -> int:
            async with free_download_slots:
                image_bytes, content_type = await self._download_page_with_retries(page_url)

            image_extension = IMAGE_EXTENSION_BY_CONTENT_TYPE.get(content_type.split(";")[0], "jpg")
            (chapter_directory / f"{page_index:04d}.{image_extension}").write_bytes(image_bytes)
            return len(image_bytes)

        try:
            # O TaskGroup cancela as outras páginas assim que uma falha de vez.
            async with asyncio.TaskGroup() as task_group:
                page_tasks = [
                    task_group.create_task(download_page(page_index, page_url))
                    for page_index, page_url in enumerate(page_urls)
                ]
        except ExceptionGroup as failures:
            raise SendJobError(f"Não deu para baixar uma página do capítulo {chapter.name}: {failures.exceptions[0]}") from None

        return DownloadedChapter(
            chapter_id=chapter.id,
            chapter_number=chapter.chapter_number,
            pages_directory=chapter_directory,
            size_in_bytes=sum(task.result() for task in page_tasks),
        )

    async def _download_page_with_retries(self, page_url: str) -> tuple[bytes, str]:
        for attempt in range(1, PAGE_DOWNLOAD_ATTEMPTS + 1):
            try:
                return await self._suwayomi.download_image(page_url)
            except httpx.HTTPError:
                if attempt == PAGE_DOWNLOAD_ATTEMPTS:
                    raise
                await asyncio.sleep(SECONDS_BEFORE_PAGE_RETRY * attempt)

    async def _convert_and_send_bundles(
        self,
        job: SendJob,
        manga_title: str,
        source_name: str,
        downloaded_chapters: list[DownloadedChapter],
        work_directory: Path,
    ) -> None:
        pending_bundles = deque(group_chapters_by_size(downloaded_chapters, self._max_attachment_bytes))
        total_chapters = len(downloaded_chapters)
        sent_chapter_count = 0
        bundle_number = 0

        while pending_bundles:
            bundle = pending_bundles.popleft()
            bundle_number += 1
            chapter_range = format_chapter_range(bundle[0].chapter_number, bundle[-1].chapter_number)
            sent_so_far = f"{sent_chapter_count} de {total_chapters} capítulos enviados"

            self._database.update_job_progress(job.id, f"Convertendo {chapter_range} · {sent_so_far}")
            book_title = build_book_title(source_name, manga_title, bundle[0].chapter_number, bundle[-1].chapter_number)
            book_path = await self._convert_bundle(bundle, work_directory / "lotes" / f"{bundle_number:04d}", book_title, source_name)

            if book_path.stat().st_size > self._max_attachment_bytes:
                if len(bundle) == 1:
                    raise SendJobError(
                        f"O capítulo {bundle[0].chapter_number} fica maior que "
                        f"{self._settings.max_attachment_megabytes} MB mesmo convertido."
                    )
                first_half, second_half = split_bundle_in_half(bundle)
                pending_bundles.appendleft(second_half)
                pending_bundles.appendleft(first_half)
                continue

            self._stop_if_daily_email_limit_reached()
            self._database.update_job_progress(job.id, f"Enviando {chapter_range} por e-mail · {sent_so_far}")
            await asyncio.to_thread(send_book_to_kindle, self._settings, book_path, book_title)
            self._database.record_sent_email(job.id, book_title)
            self._database.record_sent_chapters(job.id, job.manga_id, [chapter.chapter_id for chapter in bundle])
            sent_chapter_count += len(bundle)

    def _stop_if_daily_email_limit_reached(self) -> None:
        """Os lotes já enviados ficam registrados, então o "Tentar de novo" continua de onde parou."""
        email_times = self._database.email_times_in_last_day()
        if len(email_times) < self._settings.max_emails_per_day:
            return

        oldest_email_in_window = email_times[-self._settings.max_emails_per_day]
        next_free_slot = oldest_email_in_window + timedelta(days=1)
        raise SendJobError(
            f"Limite de {self._settings.max_emails_per_day} e-mails em 24 horas atingido. "
            f"Tente de novo depois de {next_free_slot.strftime('%d/%m %H:%M')}."
        )

    async def _convert_bundle(
        self, bundle: list[DownloadedChapter], bundle_directory: Path, book_title: str, source_name: str
    ) -> Path:
        pages_directory = bundle_directory / "paginas"
        for chapter in bundle:
            shutil.copytree(chapter.pages_directory, pages_directory / chapter.pages_directory.name)

        return await asyncio.to_thread(
            convert_to_epub,
            pages_directory,
            bundle_directory / "epub",
            book_title,
            source_name,
            self._settings.kindle_profile,
        )
