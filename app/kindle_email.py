import re
import smtplib
from email.message import EmailMessage
from pathlib import Path

from settings import Settings

SMTP_SSL_PORT = 465

# Caracteres que não podem aparecer em nome de arquivo no Windows, no Kindle ou em anexos de e-mail.
FORBIDDEN_FILENAME_CHARACTERS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def build_attachment_filename(book_title: str) -> str:
    """O Send to Kindle usa o nome do anexo como título do livro, então ele precisa ser o título."""
    safe_title = FORBIDDEN_FILENAME_CHARACTERS.sub(" ", book_title)
    safe_title = re.sub(r"\s+", " ", safe_title).strip(" .")
    return f"{safe_title or 'manga'}.epub"


def build_kindle_email(settings: Settings, book_path: Path, book_title: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = settings.sender_email
    message["To"] = settings.kindle_email
    message["Subject"] = book_title
    message.set_content(f"{book_title}\n\nEnviado pelo MangaKindle.")
    message.add_attachment(
        book_path.read_bytes(),
        maintype="application",
        subtype="epub+zip",
        filename=build_attachment_filename(book_title),
    )
    return message


def send_book_to_kindle(settings: Settings, book_path: Path, book_title: str) -> None:
    message = build_kindle_email(settings, book_path, book_title)

    if settings.smtp_port == SMTP_SSL_PORT:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port) as smtp:
            smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
        return

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
        smtp.starttls()
        smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)
