from dataclasses import dataclass

import httpx

# Fonte "Local source" do Suwayomi, que lê arquivos do próprio servidor. Não interessa ao app.
LOCAL_SOURCE_ID = "0"


@dataclass(frozen=True)
class Extension:
    package_name: str
    name: str
    language: str
    version: str
    icon_url: str
    is_installed: bool
    has_update: bool
    is_nsfw: bool


@dataclass(frozen=True)
class Source:
    id: str
    display_name: str
    language: str
    icon_url: str


@dataclass(frozen=True)
class MangaSummary:
    id: int
    title: str
    thumbnail_url: str | None


@dataclass(frozen=True)
class Chapter:
    id: int
    name: str
    chapter_number: float
    scanlator: str | None
    source_order: int


@dataclass(frozen=True)
class MangaDetails:
    id: int
    title: str
    author: str | None
    description: str | None
    thumbnail_url: str | None
    source_name: str
    chapters: list[Chapter]


class SuwayomiError(Exception):
    pass


class SuwayomiClient:
    def __init__(self, base_url: str, timeout_seconds: float = 120):
        self.base_url = base_url
        self._http = httpx.AsyncClient(base_url=base_url, timeout=timeout_seconds)

    async def close(self) -> None:
        await self._http.aclose()

    async def _graphql(self, query: str, variables: dict | None = None) -> dict:
        response = await self._http.post("/api/graphql", json={"query": query, "variables": variables or {}})
        response.raise_for_status()
        body = response.json()

        if body.get("errors"):
            messages = "; ".join(error["message"] for error in body["errors"])
            raise SuwayomiError(messages)

        return body["data"]

    async def list_extension_store_urls(self) -> list[str]:
        data = await self._graphql("{ extensionStores { nodes { indexUrl } } }")
        return [store["indexUrl"] for store in data["extensionStores"]["nodes"]]

    async def add_extension_store(self, index_url: str) -> None:
        await self._graphql(
            "mutation($url: String!) { addExtensionStore(input: { indexUrl: $url }) { extensionStore { indexUrl } } }",
            {"url": index_url},
        )

    async def remove_extension_store(self, index_url: str) -> None:
        await self._graphql(
            "mutation($url: String!) { removeExtensionStore(input: { indexUrl: $url }) { clientMutationId } }",
            {"url": index_url},
        )

    async def refresh_extensions(self) -> None:
        """Baixa de novo a lista de extensões de todos os repositórios cadastrados."""
        await self._graphql("mutation { fetchExtensions(input: {}) { clientMutationId } }")

    async def list_extensions(self) -> list[Extension]:
        data = await self._graphql(
            """
            {
              extensions {
                nodes { pkgName name lang versionName iconUrl isInstalled hasUpdate contentWarning }
              }
            }
            """
        )
        return [
            Extension(
                package_name=extension["pkgName"],
                name=extension["name"],
                language=extension["lang"],
                version=extension["versionName"],
                icon_url=extension["iconUrl"],
                is_installed=extension["isInstalled"],
                has_update=extension["hasUpdate"],
                is_nsfw=extension["contentWarning"] == "NSFW",
            )
            for extension in data["extensions"]["nodes"]
        ]

    async def install_extension(self, package_name: str) -> None:
        await self._update_extension(package_name, {"install": True})

    async def update_extension(self, package_name: str) -> None:
        await self._update_extension(package_name, {"update": True})

    async def uninstall_extension(self, package_name: str) -> None:
        await self._update_extension(package_name, {"uninstall": True})

    async def _update_extension(self, package_name: str, patch: dict) -> None:
        await self._graphql(
            """
            mutation($id: String!, $patch: UpdateExtensionPatchInput!) {
              updateExtension(input: { id: $id, patch: $patch }) { clientMutationId }
            }
            """,
            {"id": package_name, "patch": patch},
        )

    async def list_installed_sources(self) -> list[Source]:
        data = await self._graphql("{ sources { nodes { id displayName lang iconUrl } } }")
        sources = [
            Source(id=source["id"], display_name=source["displayName"], language=source["lang"], icon_url=source["iconUrl"])
            for source in data["sources"]["nodes"]
            if source["id"] != LOCAL_SOURCE_ID
        ]
        return sorted(sources, key=lambda source: source.display_name.lower())

    async def search_manga(self, source_id: str, search_text: str, page: int = 1) -> tuple[list[MangaSummary], bool]:
        """Sem texto de busca, devolve os mangás populares da fonte."""
        fetch_type = "SEARCH" if search_text else "POPULAR"
        data = await self._graphql(
            """
            mutation($source: LongString!, $type: FetchSourceMangaType!, $query: String, $page: Int!) {
              fetchSourceManga(input: { source: $source, type: $type, query: $query, page: $page }) {
                hasNextPage
                mangas { id title thumbnailUrl }
              }
            }
            """,
            {"source": source_id, "type": fetch_type, "query": search_text or None, "page": page},
        )
        result = data["fetchSourceManga"]
        mangas = [
            MangaSummary(id=manga["id"], title=manga["title"], thumbnail_url=manga["thumbnailUrl"])
            for manga in result["mangas"]
        ]
        return mangas, result["hasNextPage"]

    async def get_manga_details(self, manga_id: int) -> MangaDetails:
        data = await self._graphql(
            """
            mutation($id: Int!) {
              fetchMangaAndChapters(input: { id: $id, fetchManga: true, fetchChapters: true }) {
                manga { id title author description thumbnailUrl source { displayName } }
                chapters { id name chapterNumber scanlator sourceOrder }
              }
            }
            """,
            {"id": manga_id},
        )
        manga = data["fetchMangaAndChapters"]["manga"]
        chapters = [
            Chapter(
                id=chapter["id"],
                name=chapter["name"],
                chapter_number=chapter["chapterNumber"],
                scanlator=chapter["scanlator"],
                source_order=chapter["sourceOrder"],
            )
            for chapter in data["fetchMangaAndChapters"]["chapters"]
        ]
        # A ordem da fonte (sourceOrder) varia entre extensões; o número do capítulo dá a ordem de leitura.
        chapters.sort(key=lambda chapter: (chapter.chapter_number, chapter.source_order))

        source_name = manga["source"]["displayName"] if manga["source"] else "Desconhecida"
        return MangaDetails(
            id=manga["id"],
            title=manga["title"],
            author=manga["author"],
            description=manga["description"],
            thumbnail_url=manga["thumbnailUrl"],
            source_name=source_name,
            chapters=chapters,
        )

    async def get_chapter_page_urls(self, chapter_id: int) -> list[str]:
        data = await self._graphql(
            "mutation($id: Int!) { fetchChapterPages(input: { chapterId: $id }) { pages } }",
            {"id": chapter_id},
        )
        return data["fetchChapterPages"]["pages"]

    async def download_image(self, image_url: str) -> tuple[bytes, str]:
        """Baixa uma imagem servida pelo Suwayomi (página ou capa) e devolve o conteúdo e o content-type."""
        response = await self._http.get(image_url)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "application/octet-stream")
        return response.content, content_type
