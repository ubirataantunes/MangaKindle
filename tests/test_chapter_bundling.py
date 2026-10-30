from pathlib import Path

from chapter_bundling import DownloadedChapter, group_chapters_by_size, split_bundle_in_half


def make_chapter(chapter_number: float, size_in_bytes: int) -> DownloadedChapter:
    return DownloadedChapter(
        chapter_id=int(chapter_number * 10),
        chapter_number=chapter_number,
        pages_directory=Path(f"/tmp/{chapter_number}"),
        size_in_bytes=size_in_bytes,
    )


def chapter_numbers(bundles: list[list[DownloadedChapter]]) -> list[list[float]]:
    return [[chapter.chapter_number for chapter in bundle] for bundle in bundles]


def test_chapters_that_fit_together_stay_in_one_bundle():
    chapters = [make_chapter(1, 30), make_chapter(2, 30), make_chapter(3, 40)]

    bundles = group_chapters_by_size(chapters, max_bundle_bytes=100)

    assert chapter_numbers(bundles) == [[1, 2, 3]]


def test_new_bundle_starts_when_limit_would_be_exceeded():
    chapters = [make_chapter(1, 60), make_chapter(2, 60), make_chapter(3, 30)]

    bundles = group_chapters_by_size(chapters, max_bundle_bytes=100)

    assert chapter_numbers(bundles) == [[1], [2, 3]]


def test_chapter_bigger_than_limit_gets_its_own_bundle():
    chapters = [make_chapter(1, 20), make_chapter(2, 500), make_chapter(3, 20)]

    bundles = group_chapters_by_size(chapters, max_bundle_bytes=100)

    assert chapter_numbers(bundles) == [[1], [2], [3]]


def test_no_chapters_means_no_bundles():
    assert group_chapters_by_size([], max_bundle_bytes=100) == []


def test_split_bundle_keeps_reading_order():
    bundle = [make_chapter(number, 10) for number in (1, 2, 3)]

    first_half, second_half = split_bundle_in_half(bundle)

    assert [chapter.chapter_number for chapter in first_half] == [1]
    assert [chapter.chapter_number for chapter in second_half] == [2, 3]
