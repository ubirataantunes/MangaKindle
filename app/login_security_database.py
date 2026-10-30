import hashlib
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

SESSION_LIFETIME = timedelta(days=7)
MAX_FAILED_LOGINS = 5
FAILED_LOGIN_WINDOW = timedelta(minutes=15)
LOGIN_BLOCK_DURATION = timedelta(minutes=15)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_session_id(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()


class LoginSecurityDatabase:
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
                CREATE TABLE IF NOT EXISTS sessions (
                    session_hash TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS failed_logins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_ip TEXT NOT NULL,
                    attempted_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_failed_logins_client_ip ON failed_logins (client_ip);
                """
            )

    def create_session(self, now: datetime | None = None) -> str:
        now = now or _utc_now()
        session_id = secrets.token_urlsafe(32)
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sessions (session_hash, created_at, expires_at) VALUES (?, ?, ?)",
                (_hash_session_id(session_id), now.isoformat(), (now + SESSION_LIFETIME).isoformat()),
            )
        return session_id

    def is_session_active(self, session_id: str, now: datetime | None = None) -> bool:
        now = now or _utc_now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT expires_at FROM sessions WHERE session_hash = ?", (_hash_session_id(session_id),)
            ).fetchone()
        if row is None:
            return False
        return datetime.fromisoformat(row["expires_at"]) > now

    def end_session(self, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE session_hash = ?", (_hash_session_id(session_id),))

    def end_all_sessions(self) -> int:
        with self._connect() as connection:
            return connection.execute("DELETE FROM sessions").rowcount

    def delete_expired_sessions(self, now: datetime | None = None) -> None:
        now = now or _utc_now()
        with self._connect() as connection:
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (now.isoformat(),))

    def record_failed_login(self, client_ip: str, now: datetime | None = None) -> None:
        now = now or _utc_now()
        with self._connect() as connection:
            connection.execute("DELETE FROM failed_logins WHERE attempted_at < ?", ((now - FAILED_LOGIN_WINDOW).isoformat(),))
            connection.execute(
                "INSERT INTO failed_logins (client_ip, attempted_at) VALUES (?, ?)", (client_ip, now.isoformat())
            )

    def is_login_blocked(self, client_ip: str, now: datetime | None = None) -> bool:
        now = now or _utc_now()
        window_start = now - FAILED_LOGIN_WINDOW
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT attempted_at FROM failed_logins WHERE client_ip = ? ORDER BY attempted_at", (client_ip,)
            ).fetchall()

        attempts_in_window = [
            attempted_at
            for attempted_at in (datetime.fromisoformat(row["attempted_at"]) for row in rows)
            if attempted_at >= window_start
        ]
        if len(attempts_in_window) < MAX_FAILED_LOGINS:
            return False

        last_attempt = attempts_in_window[-1]
        return now - last_attempt < LOGIN_BLOCK_DURATION

    def clear_failed_logins(self, client_ip: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM failed_logins WHERE client_ip = ?", (client_ip,))
