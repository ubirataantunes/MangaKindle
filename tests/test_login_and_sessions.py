import logging
from datetime import datetime, timedelta, timezone
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

import main
from login import client_ip
from login_security_database import (
    FAILED_LOGIN_WINDOW,
    LOGIN_BLOCK_DURATION,
    MAX_FAILED_LOGINS,
    SESSION_LIFETIME,
)
from tests.conftest import TEST_PASSWORD, log_in, read_csrf_token

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
SESSION_COOKIE = "mangakindle_sessao"


def fail_login(client: TestClient, headers: dict | None = None):
    token = read_csrf_token(client)
    return client.post(
        "/login", data={"senha": "errada", "csrf_token": token}, headers=headers or {}, follow_redirects=False
    )


def fake_request(peer: str | None, headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "headers": [(name.lower().encode(), value.encode()) for name, value in headers.items()],
        "client": (peer, 5000) if peer else None,
    }
    return Request(scope)


# ---------- limite de tentativas ----------

def test_five_failures_then_login_is_blocked_with_429_even_with_correct_password(client):
    for _ in range(MAX_FAILED_LOGINS):
        assert fail_login(client).status_code == 401

    response = log_in(client)

    assert response.status_code == 429
    assert "Muitas tentativas" in response.text


def test_four_failures_do_not_block(client):
    for _ in range(MAX_FAILED_LOGINS - 1):
        fail_login(client)

    assert log_in(client).status_code == 303


def test_successful_login_clears_previous_failures(client, login_security):
    for _ in range(MAX_FAILED_LOGINS - 1):
        fail_login(client)
    assert log_in(client).status_code == 303
    client.cookies.clear()

    for _ in range(MAX_FAILED_LOGINS - 1):
        assert fail_login(client).status_code == 401

    assert not login_security.is_login_blocked("testclient")


def test_block_lasts_until_the_block_duration_passes(login_security):
    for _ in range(MAX_FAILED_LOGINS):
        login_security.record_failed_login("203.0.113.9", now=NOW)

    assert login_security.is_login_blocked("203.0.113.9", now=NOW + timedelta(minutes=1))
    assert login_security.is_login_blocked("203.0.113.9", now=NOW + LOGIN_BLOCK_DURATION - timedelta(seconds=1))
    assert not login_security.is_login_blocked("203.0.113.9", now=NOW + LOGIN_BLOCK_DURATION + timedelta(seconds=1))


def test_failures_outside_the_window_do_not_count(login_security):
    old = NOW - FAILED_LOGIN_WINDOW - timedelta(minutes=1)
    for _ in range(MAX_FAILED_LOGINS - 1):
        login_security.record_failed_login("203.0.113.9", now=old)
    login_security.record_failed_login("203.0.113.9", now=NOW)

    assert not login_security.is_login_blocked("203.0.113.9", now=NOW)


def test_block_is_per_ip(login_security):
    for _ in range(MAX_FAILED_LOGINS):
        login_security.record_failed_login("203.0.113.9", now=NOW)

    assert not login_security.is_login_blocked("203.0.113.10", now=NOW)


def test_clear_failed_logins_unblocks(login_security):
    for _ in range(MAX_FAILED_LOGINS):
        login_security.record_failed_login("203.0.113.9", now=NOW)

    login_security.clear_failed_logins("203.0.113.9")

    assert not login_security.is_login_blocked("203.0.113.9", now=NOW)


# ---------- IP do cliente ----------

def test_cf_connecting_ip_is_ignored_when_peer_is_not_a_trusted_proxy():
    request = fake_request("198.51.100.7", {"CF-Connecting-IP": "203.0.113.50"})

    assert client_ip(request, frozenset({"172.30.0.2"})) == "198.51.100.7"


def test_cf_connecting_ip_is_used_when_peer_is_a_trusted_proxy():
    request = fake_request("172.30.0.2", {"CF-Connecting-IP": "203.0.113.50"})

    assert client_ip(request, frozenset({"172.30.0.2"})) == "203.0.113.50"


def test_x_forwarded_for_is_never_used():
    request = fake_request("198.51.100.7", {"X-Forwarded-For": "203.0.113.50"})

    assert client_ip(request, frozenset({"198.51.100.7"})) == "198.51.100.7"


@pytest.mark.parametrize("invalid_header", ["", "nao-e-ip", "999.1.1.1", "1.2.3.4, 5.6.7.8"])
def test_invalid_cf_connecting_ip_falls_back_to_peer(invalid_header):
    request = fake_request("172.30.0.2", {"CF-Connecting-IP": invalid_header})

    assert client_ip(request, frozenset({"172.30.0.2"})) == "172.30.0.2"


def test_forged_cf_header_does_not_evade_the_block_from_an_untrusted_peer(client):
    for attempt in range(MAX_FAILED_LOGINS):
        fail_login(client, headers={"CF-Connecting-IP": f"203.0.113.{attempt + 1}"})

    response = fail_login(client, headers={"CF-Connecting-IP": "203.0.113.200"})

    assert response.status_code == 429


def test_failures_are_counted_per_real_ip_behind_a_trusted_proxy(client, monkeypatch):
    monkeypatch.setattr(main, "settings", replace(main.settings, trusted_proxy_ips=frozenset({"testclient"})))
    for _ in range(MAX_FAILED_LOGINS):
        fail_login(client, headers={"CF-Connecting-IP": "203.0.113.1"})

    blocked = fail_login(client, headers={"CF-Connecting-IP": "203.0.113.1"})
    other_visitor = fail_login(client, headers={"CF-Connecting-IP": "203.0.113.2"})

    assert blocked.status_code == 429
    assert other_visitor.status_code == 401


# ---------- sessões ----------

def test_login_sets_a_seven_day_cookie(client):
    response = log_in(client)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    cookie = response.headers["set-cookie"]
    assert SESSION_COOKIE in cookie
    assert f"Max-Age={int(SESSION_LIFETIME.total_seconds())}" in cookie
    assert "httponly" in cookie.lower()
    assert "samesite=lax" in cookie.lower()


def test_wrong_password_returns_401_and_does_not_log_in(client):
    assert fail_login(client).status_code == 401

    assert client.get("/buscar", follow_redirects=False).status_code == 303


def test_logout_invalidates_the_session_on_the_server(logged_client):
    old_cookie = logged_client.cookies.get(SESSION_COOKIE)
    token = read_csrf_token(logged_client, "/buscar")

    response = logged_client.post("/logout", data={"csrf_token": token}, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/login"

    replayed = TestClient(main.app_with_security_headers, cookies={SESSION_COOKIE: old_cookie})
    reused = replayed.get("/buscar", follow_redirects=False)
    assert reused.status_code == 303
    assert reused.headers["location"] == "/login"


def test_end_all_sessions_invalidates_other_sessions(fake_suwayomi):
    first = TestClient(main.app_with_security_headers)
    second = TestClient(main.app_with_security_headers)
    log_in(first)
    log_in(second)
    token = read_csrf_token(first, "/buscar")

    response = first.post("/sessoes/encerrar-todas", data={"csrf_token": token}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"
    assert second.get("/buscar", follow_redirects=False).headers["location"] == "/login"
    assert first.get("/buscar", follow_redirects=False).headers["location"] == "/login"


def test_session_expires_after_seven_days(login_security):
    session_id = login_security.create_session(now=NOW)

    assert login_security.is_session_active(session_id, now=NOW + SESSION_LIFETIME - timedelta(seconds=1))
    assert not login_security.is_session_active(session_id, now=NOW + SESSION_LIFETIME + timedelta(seconds=1))


def test_unknown_session_id_is_not_active(login_security):
    assert not login_security.is_session_active("id-que-nao-existe")


def test_end_session_and_end_all_sessions(login_security):
    first = login_security.create_session(now=NOW)
    second = login_security.create_session(now=NOW)
    third = login_security.create_session(now=NOW)

    login_security.end_session(first)
    assert not login_security.is_session_active(first, now=NOW)
    assert login_security.is_session_active(second, now=NOW)

    assert login_security.end_all_sessions() == 2
    assert not login_security.is_session_active(second, now=NOW)
    assert not login_security.is_session_active(third, now=NOW)


def test_delete_expired_sessions_keeps_active_ones(login_security):
    expired = login_security.create_session(now=NOW - timedelta(days=30))
    active = login_security.create_session(now=NOW)

    login_security.delete_expired_sessions(now=NOW)

    assert not login_security.is_session_active(expired, now=NOW - timedelta(days=30) + timedelta(hours=1))
    assert login_security.is_session_active(active, now=NOW)


def test_raw_session_id_is_not_stored_in_the_database(login_security, tmp_path):
    session_id = login_security.create_session(now=NOW)

    database_bytes = (tmp_path / "seguranca.sqlite").read_bytes()

    assert session_id.encode() not in database_bytes


def test_session_ids_are_unpredictable(login_security):
    ids = {login_security.create_session(now=NOW) for _ in range(20)}

    assert len(ids) == 20
    assert all(len(session_id) >= 32 for session_id in ids)


# ---------- logs ----------

def test_failed_login_is_logged_with_ip_and_without_the_password(client, caplog):
    token = read_csrf_token(client)

    with caplog.at_level(logging.INFO):
        client.post("/login", data={"senha": "minha-senha-secreta", "csrf_token": token})

    assert "testclient" in caplog.text
    assert "minha-senha-secreta" not in caplog.text
    assert token not in caplog.text


def test_successful_login_does_not_log_secrets(client, caplog):
    with caplog.at_level(logging.DEBUG):
        log_in(client)

    assert TEST_PASSWORD not in caplog.text
    assert main.settings.app_password_hash not in caplog.text
