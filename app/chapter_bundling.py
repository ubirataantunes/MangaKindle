from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DownloadedChapter:
    chapter_id: int
    chapter_number: float
    pages_directory: Path
    size_in_bytes: int


def group_chapters_by_size(chapters: list[DownloadedChapter], max_bundle_bytes: int) -> list[list[DownloadedChapter]]:
    """Junta capítulos consecutivos em lotes que caibam em um anexo.

    Um capítulo maior que o limite fica sozinho no próprio lote; a conversão para EPUB
    costuma reduzir o tamanho, então ele ainda pode caber depois de convertido.
    """
    bundles: list[list[DownloadedChapter]] = []
    current_bundle: list[DownloadedChapter] = []
    current_bundle_bytes = 0

    for chapter in chapters:
        exceeds_limit = current_bundle_bytes + chapter.size_in_bytes > max_bundle_bytes

        if current_bundle and exceeds_limit:
            bundles.append(current_bundle)
            current_bundle = []
            current_bundle_bytes = 0

        current_bundle.append(chapter)
        current_bundle_bytes += chapter.size_in_bytes

    if current_bundle:
        bundles.append(current_bundle)

    return bundles


def split_bundle_in_half(bundle: list[DownloadedChapter]) -> tuple[list[DownloadedChapter], list[DownloadedChapter]]:
    middle = len(bundle) // 2
    return bundle[:middle], bundle[middle:]
