import re
from urllib.parse import urlparse

MAX_CHAPTERS_PER_SEND = 200
MAX_SEARCH_TEXT_LENGTH = 200
MAX_FILTER_TEXT_LENGTH = 100
MAX_STORE_URL_LENGTH = 500
STORE_INDEX_EXTENSIONS = (".json", ".pb")
MAX_PAGE_NUMBER = 1000

PACKAGE_NAME_PATTERN = re.compile(r"[A-Za-z0-9._]{1,200}")
SOURCE_ID_PATTERN = re.compile(r"\d{1,20}")

# Só estes caminhos da API do Suwayomi podem ser buscados pelo proxy de imagens.
ALLOWED_IMAGE_PATH_PATTERNS = (
    re.compile(r"/api/v1/manga/[1-9][0-9]{0,17}/thumbnail"),
    re.compile(r"/api/v1/extension/icon/[A-Za-z0-9][A-Za-z0-9._-]{0,199}"),
)
FORBIDDEN_IMAGE_PATH_PARTS = ("..", "%", "\\", "//", "?", "#")


class InvalidInput(Exception):
    """Entrada recusada; a mensagem em português é mostrada ao usuário."""


def validate_extension_store_url(url: str) -> str:
    clean_url = url.strip()
    if len(clean_url) > MAX_STORE_URL_LENGTH:
        raise InvalidInput(f"A URL do repositório deve ter no máximo {MAX_STORE_URL_LENGTH} caracteres.")

    try:
        parsed_url = urlparse(clean_url)
        host = parsed_url.hostname
    except ValueError:
        raise InvalidInput("URL de repositório inválida.") from None

    if parsed_url.scheme != "https" or not host:
        raise InvalidInput("A URL do repositório deve começar com https://.")
    if parsed_url.username or parsed_url.password:
        raise InvalidInput("A URL do repositório não pode ter usuário ou senha.")
    # O Mihon aceita o índice antigo em JSON e o novo em protobuf (.pb).
    if not parsed_url.path.endswith(STORE_INDEX_EXTENSIONS):
        raise InvalidInput("A URL do repositório deve terminar em .json ou .pb.")

    return clean_url


def validate_package_name(package_name: str) -> str:
    if not PACKAGE_NAME_PATTERN.fullmatch(package_name):
        raise InvalidInput("Nome de pacote da extensão inválido.")
    return package_name


def validate_source_id(source_id: str) -> str:
    if source_id and not SOURCE_ID_PATTERN.fullmatch(source_id):
        raise InvalidInput("Fonte inválida.")
    return source_id


def validate_chapter_ids(chapter_ids: list[int]) -> list[int]:
    if len(chapter_ids) > MAX_CHAPTERS_PER_SEND:
        raise InvalidInput(f"Selecione no máximo {MAX_CHAPTERS_PER_SEND} capítulos por envio.")
    if any(chapter_id <= 0 for chapter_id in chapter_ids):
        raise InvalidInput("Capítulo inválido.")
    return chapter_ids


def is_allowed_image_path(path: str) -> bool:
    if not path.startswith("/") or any(ord(character) < 32 or ord(character) == 127 for character in path):
        return False
    if any(forbidden_part in path for forbidden_part in FORBIDDEN_IMAGE_PATH_PARTS):
        return False
    return any(pattern.fullmatch(path) for pattern in ALLOWED_IMAGE_PATH_PATTERNS)
