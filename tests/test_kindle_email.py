from kindle_email import build_attachment_filename, build_kindle_email
from tests.test_send_queue import make_settings


def test_attachment_is_named_after_the_book_title():
    assert build_attachment_filename("[1Manga.co (EN)] 20th Century Boys - Cap. 398-401") == (
        "[1Manga.co (EN)] 20th Century Boys - Cap. 398-401.epub"
    )


def test_forbidden_characters_are_removed_from_the_filename():
    assert build_attachment_filename('[Fonte] Re:Zero / Parte "2"? - Cap. 1') == "[Fonte] Re Zero Parte 2 - Cap. 1.epub"


def test_empty_title_still_gets_a_filename():
    assert build_attachment_filename(" ?? ") == "manga.epub"


def test_email_carries_the_book_with_the_title_as_filename(tmp_path):
    book_path = tmp_path / "paginas.epub"
    book_path.write_bytes(b"conteudo do epub")
    title = "[1Manga.co (EN)] 20th Century Boys - Cap. 398-401"

    message = build_kindle_email(make_settings(tmp_path), book_path, title)

    attachment = next(message.iter_attachments())
    assert attachment.get_filename() == f"{title}.epub"
    assert attachment.get_content_type() == "application/epub+zip"
    assert attachment.get_content() == b"conteudo do epub"
    assert message["To"] == "eu@kindle.com"
    assert message["Subject"] == title
