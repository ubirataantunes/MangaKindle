import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Form, Query, Request
from fastapi import Path as PathParameter
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from history_database import STATUS_PENDING, STATUS_PROCESSING, HistoryDatabase
from input_validation import (
    MAX_FILTER_TEXT_LENGTH,
    MAX_PAGE_NUMBER,
    MAX_SEARCH_TEXT_LENGTH,
    MAX_STORE_URL_LENGTH,
    InvalidInput,
    is_allowed_image_path,
    validate_chapter_ids,
    validate_extension_store_url,
    validate_package_name,
    validate_source_id,
)
from kindle_conversion import format_chapter_number
from login import (
    SESSION_ID_KEY,
    CsrfTokenInvalid,
    LoginRequired,
    client_ip,
    csrf_token,
    is_correct_password,
    is_logged_in,
    is_login_enabled,
    redirect_to_login,
    require_csrf_token,
    require_login,
)
from login_security_database import SESSION_LIFETIME, LoginSecurityDatabase
from security_headers import SecurityHeadersMiddleware
from send_queue import SendQueueWorker
from settings import load_settings
from suwayomi_client import SuwayomiClient, SuwayomiError

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

settings = load_settings()
database = HistoryDatabase(settings.data_directory / "historico.sqlite")
login_security = LoginSecurityDatabase(settings.data_directory / "seguranca.sqlite")
suwayomi = SuwayomiClient(settings.suwayomi_url)
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
templates.env.filters["numero_capitulo"] = format_chapter_number
templates.env.globals["csrf_token"] = csrf_token
templates.env.globals["is_logged_in"] = is_logged_in
templates.env.globals["is_login_enabled"] = is_login_enabled


@asynccontextmanager
async def lifespan(app: FastAPI):
    login_security.delete_expired_sessions()
    worker = SendQueueWorker(settings, database, suwayomi)
    worker_task = asyncio.create_task(worker.run_forever())
    yield
    worker_task.cancel()
    await suwayomi.close()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.state.login_security = login_security
app.state.login_enabled = settings.login_enabled
if not settings.login_enabled:
    logger.warning("Login desligado (LOGIN_ENABLED=false). Use só no computador local.")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="mangakindle_sessao",
    max_age=int(SESSION_LIFETIME.total_seconds()),
    same_site="lax",
    https_only=settings.secure_cookies,
)
app.add_exception_handler(LoginRequired, redirect_to_login)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")

logged_in = [Depends(require_login)]
logged_in_with_csrf = [Depends(require_login), Depends(require_csrf_token)]


@app.exception_handler(SuwayomiError)
@app.exception_handler(httpx.HTTPError)
async def show_suwayomi_error(request: Request, error: Exception):
    logger.warning("Falha ao falar com o Suwayomi: %s: %s", error.__class__.__name__, error)
    return templates.TemplateResponse(
        request,
        "erro.html",
        {"mensagem": "O Suwayomi não respondeu como esperado. Tente de novo em instantes."},
        status_code=502,
    )


@app.exception_handler(CsrfTokenInvalid)
async def show_csrf_error(request: Request, error: CsrfTokenInvalid):
    return templates.TemplateResponse(
        request,
        "erro.html",
        {"titulo": "Formulário expirado", "mensagem": "Recarregue a página e tente de novo."},
        status_code=403,
    )


@app.exception_handler(RequestValidationError)
async def show_validation_error(request: Request, error: RequestValidationError):
    return templates.TemplateResponse(
        request,
        "erro.html",
        {"titulo": "Dados inválidos", "mensagem": "Confira os dados enviados e tente de novo."},
        status_code=422,
    )


@app.exception_handler(InvalidInput)
async def show_invalid_input(request: Request, error: InvalidInput):
    return templates.TemplateResponse(
        request, "erro.html", {"titulo": "Dados inválidos", "mensagem": str(error)}, status_code=400
    )


@app.get("/login")
async def login_page(request: Request):
    if not is_login_enabled(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"erro": None})


@app.post("/login", dependencies=[Depends(require_csrf_token)])
async def login(request: Request, senha: str = Form(..., max_length=1000)):
    if not is_login_enabled(request):
        return RedirectResponse("/", status_code=303)

    ip = client_ip(request, settings.trusted_proxy_ips)

    if login_security.is_login_blocked(ip):
        return templates.TemplateResponse(
            request, "login.html", {"erro": "Muitas tentativas. Tente de novo em 15 minutos."}, status_code=429
        )

    if not is_correct_password(senha, settings.app_password_hash):
        login_security.record_failed_login(ip)
        logger.warning("Falha de login do IP %s", ip)
        return templates.TemplateResponse(request, "login.html", {"erro": "Senha incorreta."}, status_code=401)

    login_security.clear_failed_logins(ip)
    request.session.clear()
    request.session[SESSION_ID_KEY] = login_security.create_session()
    csrf_token(request)
    return RedirectResponse("/", status_code=303)


@app.post("/logout", dependencies=logged_in_with_csrf)
async def logout(request: Request):
    login_security.end_session(request.session.get(SESSION_ID_KEY, ""))
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.post("/sessoes/encerrar-todas", dependencies=logged_in_with_csrf)
async def end_all_sessions(request: Request):
    login_security.end_all_sessions()
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/", dependencies=logged_in)
async def home():
    return RedirectResponse("/buscar", status_code=303)


@app.get("/extensoes", dependencies=logged_in)
async def extensions_page(
    request: Request,
    filtro: str = Query("", max_length=MAX_FILTER_TEXT_LENGTH),
    idioma: str = Query("", max_length=20),
    somente_instaladas: bool = False,
):
    store_urls = await suwayomi.list_extension_store_urls()
    extensions = await suwayomi.list_extensions()
    languages = sorted({extension.language for extension in extensions})

    name_filter = filtro.strip().lower()
    visible_extensions = []
    for extension in extensions:
        if name_filter and name_filter not in extension.name.lower():
            continue
        if idioma and extension.language != idioma:
            continue
        if somente_instaladas and not extension.is_installed:
            continue
        visible_extensions.append(extension)

    # Instaladas primeiro, depois em ordem alfabética.
    visible_extensions.sort(key=lambda extension: (not extension.is_installed, extension.name.lower()))

    return templates.TemplateResponse(
        request,
        "extensoes.html",
        {
            "repositorios": store_urls,
            "extensoes": visible_extensions,
            "idiomas": languages,
            "filtro": filtro,
            "idioma": idioma,
            "somente_instaladas": somente_instaladas,
        },
    )


@app.post("/extensoes/repositorios", dependencies=logged_in_with_csrf)
async def add_extension_store(url: str = Form(...)):
    await suwayomi.add_extension_store(validate_extension_store_url(url))
    await suwayomi.refresh_extensions()
    return RedirectResponse("/extensoes", status_code=303)


@app.post("/extensoes/repositorios/remover", dependencies=logged_in_with_csrf)
async def remove_extension_store(url: str = Form(..., max_length=MAX_STORE_URL_LENGTH)):
    await suwayomi.remove_extension_store(url)
    return RedirectResponse("/extensoes", status_code=303)


@app.post("/extensoes/atualizar-lista", dependencies=logged_in_with_csrf)
async def refresh_extension_list():
    await suwayomi.refresh_extensions()
    return RedirectResponse("/extensoes", status_code=303)


@app.post("/extensoes/{package_name}/instalar", dependencies=logged_in_with_csrf)
async def install_extension(package_name: str):
    await suwayomi.install_extension(validate_package_name(package_name))
    return RedirectResponse("/extensoes?somente_instaladas=true", status_code=303)


@app.post("/extensoes/{package_name}/atualizar", dependencies=logged_in_with_csrf)
async def update_extension(package_name: str):
    await suwayomi.update_extension(validate_package_name(package_name))
    return RedirectResponse("/extensoes?somente_instaladas=true", status_code=303)


@app.post("/extensoes/{package_name}/remover", dependencies=logged_in_with_csrf)
async def uninstall_extension(package_name: str):
    await suwayomi.uninstall_extension(validate_package_name(package_name))
    return RedirectResponse("/extensoes?somente_instaladas=true", status_code=303)


@app.get("/buscar", dependencies=logged_in)
async def search_page(
    request: Request,
    fonte: str = "",
    texto: str = Query("", max_length=MAX_SEARCH_TEXT_LENGTH),
    pagina: int = Query(1, ge=1, le=MAX_PAGE_NUMBER),
):
    validate_source_id(fonte)
    sources = await suwayomi.list_installed_sources()
    mangas = []
    has_next_page = False

    if fonte:
        mangas, has_next_page = await suwayomi.search_manga(fonte, texto.strip(), pagina)

    return templates.TemplateResponse(
        request,
        "buscar.html",
        {
            "fontes": sources,
            "fonte": fonte,
            "texto": texto,
            "pagina": pagina,
            "mangas": mangas,
            "tem_proxima_pagina": has_next_page,
        },
    )


@app.get("/manga/{manga_id}", dependencies=logged_in)
async def manga_page(request: Request, manga_id: int = PathParameter(gt=0)):
    manga = await suwayomi.get_manga_details(manga_id)
    sent_chapter_ids = database.sent_chapter_ids(manga_id)
    queued_chapter_ids = database.queued_chapter_ids(manga_id) - sent_chapter_ids
    return templates.TemplateResponse(
        request,
        "manga.html",
        {
            "manga": manga,
            "enviados": sent_chapter_ids,
            "na_fila": queued_chapter_ids,
            "favorito": database.is_favorite(manga_id),
            "lidos": database.read_chapter_ids(manga_id),
        },
    )


@app.post("/manga/{manga_id}/favoritar", dependencies=logged_in_with_csrf)
async def add_favorite(manga_id: int = PathParameter(gt=0)):
    manga = await suwayomi.get_manga_details(manga_id)
    database.add_favorite(manga.id, manga.title, manga.source_name, manga.thumbnail_url)
    return RedirectResponse(f"/manga/{manga_id}", status_code=303)


@app.post("/manga/{manga_id}/desfavoritar", dependencies=logged_in_with_csrf)
async def remove_favorite(manga_id: int = PathParameter(gt=0)):
    database.remove_favorite(manga_id)
    return RedirectResponse(f"/manga/{manga_id}", status_code=303)


def back_to_chapter(manga_id: int, chapter_id: int) -> RedirectResponse:
    # A âncora faz a página voltar aberta na faixa do capítulo que acabou de ser marcado.
    return RedirectResponse(f"/manga/{manga_id}#capitulo-{chapter_id}", status_code=303)


@app.post("/manga/{manga_id}/lido", dependencies=logged_in_with_csrf)
async def mark_chapter_read(manga_id: int = PathParameter(gt=0), capitulo: int = Form(gt=0)):
    database.mark_chapters_read(manga_id, [capitulo])
    return back_to_chapter(manga_id, capitulo)


@app.post("/manga/{manga_id}/lido-ate-aqui", dependencies=logged_in_with_csrf)
async def mark_chapters_read_up_to(manga_id: int = PathParameter(gt=0), capitulo: int = Form(gt=0)):
    manga = await suwayomi.get_manga_details(manga_id)
    chapter_ids_in_reading_order = [chapter.id for chapter in manga.chapters]
    if capitulo not in chapter_ids_in_reading_order:
        return back_to_chapter(manga_id, capitulo)

    position_of_last_read = chapter_ids_in_reading_order.index(capitulo)
    database.mark_chapters_read(manga_id, chapter_ids_in_reading_order[: position_of_last_read + 1])
    return back_to_chapter(manga_id, capitulo)


@app.post("/manga/{manga_id}/nao-lido", dependencies=logged_in_with_csrf)
async def mark_chapter_unread(manga_id: int = PathParameter(gt=0), capitulo: int = Form(gt=0)):
    database.mark_chapter_unread(manga_id, capitulo)
    return back_to_chapter(manga_id, capitulo)


@app.get("/favoritos", dependencies=logged_in)
async def favorites_page(request: Request):
    return templates.TemplateResponse(request, "favoritos.html", {"favoritos": database.favorite_mangas()})


@app.post("/manga/{manga_id}/enviar", dependencies=logged_in_with_csrf)
async def send_chapters(
    manga_id: int = PathParameter(gt=0),
    capitulos: list[int] = Form(default=[]),
    reenviar: bool = Form(default=False),
):
    validate_chapter_ids(capitulos)

    # Evita pedir de novo o que já está na fila (ex.: clique duplo no botão). Os já enviados
    # só entram quando o usuário marcou explicitamente que quer reenviar.
    unavailable_ids = database.queued_chapter_ids(manga_id)
    if not reenviar:
        unavailable_ids |= database.sent_chapter_ids(manga_id)

    chapters_to_send = [chapter_id for chapter_id in capitulos if chapter_id not in unavailable_ids]
    if not chapters_to_send:
        return RedirectResponse(f"/manga/{manga_id}", status_code=303)

    manga = await suwayomi.get_manga_details(manga_id)
    database.create_job(manga.id, manga.title, manga.source_name, chapters_to_send, is_resend=reenviar)
    return RedirectResponse("/envios", status_code=303)


@app.get("/envios", dependencies=logged_in)
async def jobs_page(request: Request):
    jobs = database.recent_jobs()
    has_unfinished_job = any(job.status in (STATUS_PENDING, STATUS_PROCESSING) for job in jobs)
    return templates.TemplateResponse(
        request,
        "envios.html",
        {
            "envios": jobs,
            "atualizar_sozinho": has_unfinished_job,
            "emails_no_ultimo_dia": len(database.email_times_in_last_day()),
            "limite_emails_por_dia": settings.max_emails_per_day,
        },
    )


@app.post("/envios/{job_id}/tentar-novamente", dependencies=logged_in_with_csrf)
async def retry_job(job_id: int = PathParameter(gt=0)):
    database.retry_job(job_id)
    return RedirectResponse("/envios", status_code=303)


@app.get("/imagem", dependencies=logged_in)
async def image_proxy(request: Request, caminho: str):
    """O navegador não acessa o Suwayomi diretamente, então capas e ícones passam por aqui."""
    has_only_the_path_parameter = len(request.query_params.multi_items()) == 1
    if not has_only_the_path_parameter or not is_allowed_image_path(caminho):
        return Response(status_code=404)

    try:
        image_bytes, content_type = await suwayomi.download_image(caminho)
    except httpx.HTTPError:
        return Response(status_code=404)

    return Response(image_bytes, media_type=content_type, headers={"Cache-Control": "max-age=86400"})


# O uvicorn serve este objeto. Por fora de todo o resto, ele põe os headers de segurança
# também nas respostas 500 não tratadas, que o ServerErrorMiddleware do Starlette gera.
app_with_security_headers = SecurityHeadersMiddleware(app)
