import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

STATUS_PENDING = "pendente"
STATUS_PROCESSING = "processando"
STATUS_SENT = "enviado"
STATUS_ERROR = "erro"


@dataclass(frozen=True)
class SendJob:
    id: int
    manga_id: int
    manga_title: str
    source_name: str
    chapter_ids: list[int]
    status: str
    error_message: str | None
    created_at: str
    finished_at: str | None
    progress: str | None = None
    is_resend: bool = False


@dataclass(frozen=True)
class FavoriteManga:
    manga_id: int
    title: str
    source_name: str
    thumbnail_url: str | None
    added_at: str


class HistoryDatabase:
    def __init__(self, database_path: Path):
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._database_path = database_path
        self._create_tables()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _create_tables(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS send_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    manga_id INTEGER NOT NULL,
                    manga_title TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    chapter_ids TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS sent_chapters (
                    chapter_id INTEGER PRIMARY KEY,
                    manga_id INTEGER NOT NULL,
                    job_id INTEGER NOT NULL,
                    sent_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sent_emails (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    book_title TEXT NOT NULL,
                    sent_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS read_chapters (
                    chapter_id INTEGER PRIMARY KEY,
                    manga_id INTEGER NOT NULL,
                    read_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS favorite_mangas (
                    manga_id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    thumbnail_url TEXT,
                    added_at TEXT NOT NULL
                );
                """
            )
            self._add_columns_missing_from_old_databases(connection)

    def _add_columns_missing_from_old_databases(self, connection: sqlite3.Connection) -> None:
        """Bancos criados antes do progresso e do reenvio não têm essas colunas."""
        column_names = {column["name"] for column in connection.execute("PRAGMA table_info(send_jobs)")}
        if "progress" not in column_names:
            connection.execute("ALTER TABLE send_jobs ADD COLUMN progress TEXT")
        if "is_resend" not in column_names:
            connection.execute("ALTER TABLE send_jobs ADD COLUMN is_resend INTEGER NOT NULL DEFAULT 0")

    def add_favorite(self, manga_id: int, title: str, source_name: str, thumbnail_url: str | None) -> None:
        """Favoritar de novo só atualiza título, origem e capa; a data original é mantida."""
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO favorite_mangas (manga_id, title, source_name, thumbnail_url, added_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (manga_id) DO UPDATE SET
                    title = excluded.title,
                    source_name = excluded.source_name,
                    thumbnail_url = excluded.thumbnail_url
                """,
                (manga_id, title, source_name, thumbnail_url, _now()),
            )

    def remove_favorite(self, manga_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM favorite_mangas WHERE manga_id = ?", (manga_id,))

    def is_favorite(self, manga_id: int) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT 1 FROM favorite_mangas WHERE manga_id = ?", (manga_id,)).fetchone()
            return row is not None

    def favorite_mangas(self) -> list[FavoriteManga]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM favorite_mangas ORDER BY title COLLATE NOCASE").fetchall()
            return [
                FavoriteManga(
                    manga_id=row["manga_id"],
                    title=row["title"],
                    source_name=row["source_name"],
                    thumbnail_url=row["thumbnail_url"],
                    added_at=row["added_at"],
                )
                for row in rows
            ]

    def create_job(
        self, manga_id: int, manga_title: str, source_name: str, chapter_ids: list[int], is_resend: bool = False
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO send_jobs (manga_id, manga_title, source_name, chapter_ids, status, created_at, is_resend)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (manga_id, manga_title, source_name, json.dumps(chapter_ids), STATUS_PENDING, _now(), is_resend),
            )
            return cursor.lastrowid

    def take_next_pending_job(self) -> SendJob | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM send_jobs WHERE status = ? ORDER BY id LIMIT 1",
                (STATUS_PENDING,),
            ).fetchone()
            if row is None:
                return None

            connection.execute("UPDATE send_jobs SET status = ? WHERE id = ?", (STATUS_PROCESSING, row["id"]))
            return _job_from_row(row, status=STATUS_PROCESSING)

    def mark_job_sent(self, job_id: int) -> None:
        self._finish_job(job_id, STATUS_SENT, error_message=None)

    def mark_job_failed(self, job_id: int, error_message: str) -> None:
        self._finish_job(job_id, STATUS_ERROR, error_message)

    def _finish_job(self, job_id: int, status: str, error_message: str | None) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE send_jobs SET status = ?, error_message = ?, finished_at = ?, progress = NULL WHERE id = ?",
                (status, error_message, _now(), job_id),
            )

    def update_job_progress(self, job_id: int, progress: str) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE send_jobs SET progress = ? WHERE id = ?", (progress, job_id))

    def retry_job(self, job_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE send_jobs SET status = ?, error_message = NULL, finished_at = NULL, progress = NULL
                WHERE id = ? AND status = ?
                """,
                (STATUS_PENDING, job_id, STATUS_ERROR),
            )

    def requeue_interrupted_jobs(self) -> None:
        """Jobs que estavam em processamento quando o app parou voltam para a fila."""
        with self._connect() as connection:
            connection.execute(
                "UPDATE send_jobs SET status = ?, progress = NULL WHERE status = ?",
                (STATUS_PENDING, STATUS_PROCESSING),
            )

    def record_sent_chapters(self, job_id: int, manga_id: int, chapter_ids: list[int]) -> None:
        sent_at = _now()
        with self._connect() as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO sent_chapters (chapter_id, manga_id, job_id, sent_at) VALUES (?, ?, ?, ?)",
                [(chapter_id, manga_id, job_id, sent_at) for chapter_id in chapter_ids],
            )

    def sent_chapter_ids(self, manga_id: int) -> set[int]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT chapter_id FROM sent_chapters WHERE manga_id = ?",
                (manga_id,),
            ).fetchall()
            return {row["chapter_id"] for row in rows}

    def chapter_ids_sent_by_job(self, job_id: int) -> set[int]:
        with self._connect() as connection:
            rows = connection.execute("SELECT chapter_id FROM sent_chapters WHERE job_id = ?", (job_id,)).fetchall()
            return {row["chapter_id"] for row in rows}

    def queued_chapter_ids(self, manga_id: int) -> set[int]:
        """Capítulos que estão em envios ainda não terminados (pendentes ou em processamento)."""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT chapter_ids FROM send_jobs WHERE manga_id = ? AND status IN (?, ?)",
                (manga_id, STATUS_PENDING, STATUS_PROCESSING),
            ).fetchall()

        queued_ids: set[int] = set()
        for row in rows:
            queued_ids.update(json.loads(row["chapter_ids"]))
        return queued_ids

    def record_sent_email(self, job_id: int, book_title: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sent_emails (job_id, book_title, sent_at) VALUES (?, ?, ?)",
                (job_id, book_title, _now()),
            )

    def email_times_in_last_day(self) -> list[datetime]:
        """Horários dos e-mails das últimas 24 horas, do mais antigo ao mais novo (a janela do limite do Gmail)."""
        one_day_ago = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT sent_at FROM sent_emails WHERE sent_at > ? ORDER BY sent_at",
                (one_day_ago,),
            ).fetchall()
            return [datetime.fromisoformat(row["sent_at"]) for row in rows]

    def mark_chapters_read(self, manga_id: int, chapter_ids: list[int]) -> None:
        """Marcar de novo um capítulo já lido mantém a data da primeira leitura."""
        read_at = _now()
        with self._connect() as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO read_chapters (chapter_id, manga_id, read_at) VALUES (?, ?, ?)",
                [(chapter_id, manga_id, read_at) for chapter_id in chapter_ids],
            )

    def mark_chapter_unread(self, manga_id: int, chapter_id: int) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM read_chapters WHERE manga_id = ? AND chapter_id = ?",
                (manga_id, chapter_id),
            )

    def read_chapter_ids(self, manga_id: int) -> set[int]:
        with self._connect() as connection:
            rows = connection.execute("SELECT chapter_id FROM read_chapters WHERE manga_id = ?", (manga_id,)).fetchall()
            return {row["chapter_id"] for row in rows}

    def recent_jobs(self, limit: int = 50) -> list[SendJob]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM send_jobs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            return [_job_from_row(row) for row in rows]


def _job_from_row(row: sqlite3.Row, status: str | None = None) -> SendJob:
    return SendJob(
        id=row["id"],
        manga_id=row["manga_id"],
        manga_title=row["manga_title"],
        source_name=row["source_name"],
        chapter_ids=json.loads(row["chapter_ids"]),
        status=status or row["status"],
        error_message=row["error_message"],
        created_at=row["created_at"],
        finished_at=row["finished_at"],
        progress=row["progress"],
        is_resend=bool(row["is_resend"]),
    )


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")
