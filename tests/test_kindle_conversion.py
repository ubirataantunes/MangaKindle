from pathlib import Path

from kindle_conversion import build_book_title, build_kcc_command, format_chapter_number


def test_whole_chapter_number_has_no_decimal():
    assert format_chapter_number(12.0) == "12"


def test_fractional_chapter_number_keeps_decimal():
    assert format_chapter_number(12.5) == "12.5"


def test_title_with_single_chapter():
    assert build_book_title("MangaDex", "Berserk", 3.0, 3.0) == "[MangaDex] Berserk - Cap. 3"


def test_title_with_chapter_range():
    assert build_book_title("MangaDex", "Berserk", 1.0, 10.5) == "[MangaDex] Berserk - Cap. 1-10.5"


def test_kcc_command_uses_manga_mode_epub_and_source_as_author():
    command = build_kcc_command(
        pages_directory=Path("/trabalho/paginas"),
        output_directory=Path("/trabalho/epub"),
        book_title="[MangaDex] Berserk - Cap. 1",
        source_name="MangaDex",
        kindle_profile="KPW5",
    )

    assert command[0] == "kcc-c2e"
    assert "--manga-style" in command
    assert "--stretch" in command
    assert command[command.index("--format") + 1] == "EPUB"
    assert command[command.index("--profile") + 1] == "KPW5"
    assert command[command.index("--author") + 1] == "MangaDex"
    assert command[command.index("--title") + 1] == "[MangaDex] Berserk - Cap. 1"
    assert command[-1] == str(Path("/trabalho/paginas"))
