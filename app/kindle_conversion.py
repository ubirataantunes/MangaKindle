import subprocess
from pathlib import Path


class ConversionError(Exception):
    pass


def format_chapter_number(chapter_number: float) -> str:
    if chapter_number == int(chapter_number):
        return str(int(chapter_number))
    return str(chapter_number)


def format_chapter_range(first_chapter_number: float, last_chapter_number: float) -> str:
    first_chapter = format_chapter_number(first_chapter_number)
    last_chapter = format_chapter_number(last_chapter_number)

    if first_chapter == last_chapter:
        return f"Cap. {first_chapter}"
    return f"Cap. {first_chapter}-{last_chapter}"


def build_book_title(source_name: str, manga_title: str, first_chapter_number: float, last_chapter_number: float) -> str:
    """O prefixo com a origem agrupa os mangás de cada fonte quando o Kindle ordena por título."""
    chapter_range = format_chapter_range(first_chapter_number, last_chapter_number)
    return f"[{source_name}] {manga_title} - {chapter_range}"


def build_kcc_command(
    pages_directory: Path,
    output_directory: Path,
    book_title: str,
    source_name: str,
    kindle_profile: str,
) -> list[str]:
    return [
        "kcc-c2e",
        "--profile", kindle_profile,
        "--manga-style",
        # As páginas de mangá são um pouco mais estreitas que a tela do Kindle; sem esticar
        # sobra uma faixa branca dos lados. A distorção (uns 5%) não dá para notar.
        "--stretch",
        "--format", "EPUB",
        "--title", book_title,
        # A origem vai no campo autor para que "ordenar por autor" também agrupe por fonte.
        "--author", source_name,
        "--output", str(output_directory),
        str(pages_directory),
    ]


def convert_to_epub(
    pages_directory: Path,
    output_directory: Path,
    book_title: str,
    source_name: str,
    kindle_profile: str,
) -> Path:
    output_directory.mkdir(parents=True, exist_ok=True)
    command = build_kcc_command(pages_directory, output_directory, book_title, source_name, kindle_profile)

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise ConversionError(f"O KCC falhou: {result.stderr.strip() or result.stdout.strip()}")

    generated_books = list(output_directory.glob("*.epub"))
    if not generated_books:
        raise ConversionError(f"O KCC não gerou nenhum EPUB. Saída: {result.stdout.strip()}")

    return generated_books[0]
