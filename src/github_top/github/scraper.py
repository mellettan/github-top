import asyncio
import time
from collections import Counter
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self

from aiohttp import ClientError, ClientResponse, ClientSession, ClientTimeout
from loguru import logger

from github_top.github.models import Repository, RepositoryAuthorCommitsNum
from github_top.github.rate_limit import RateLimiter

RETRY_STATUSES = frozenset({500, 502, 503, 504})
MAX_RATE_LIMIT_WAIT_SECONDS = 60.0


class GithubApiError(RuntimeError):
    """Запрос к GitHub API не удался после всех попыток."""


class GithubReposScrapper:
    """Собирает топ репозиториев GitHub по звёздам и авторов коммитов за текущие сутки (UTC).

    Все запросы проходят через семафор (MCR) и `RateLimiter` (RPS). Ответы 5xx повторяются
    с экспоненциальной задержкой, при исчерпании лимита GitHub выжидается `X-RateLimit-Reset`.
    """

    def __init__(
        self,
        access_token: str | None = None,
        max_concurrent: int = 5,
        max_rps: float = 10.0,
        api_url: str = "https://api.github.com",
        max_commit_pages: int = 10,
        max_retries: int = 3,
        session: ClientSession | None = None,
    ) -> None:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        self._session = session or ClientSession(headers=headers, timeout=ClientTimeout(total=30))
        self._owns_session = session is None
        self._api_url = api_url.rstrip("/")
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._rate_limiter = RateLimiter(max_rps)
        self._max_commit_pages = max_commit_pages
        self._max_retries = max_retries

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_session:
            await self._session.close()

    async def get_repositories(self, limit: int = 100) -> list[Repository]:
        """Топ `limit` репозиториев с авторами коммитов за сегодня, в порядке позиции."""
        repositories = [repository async for repository in self.iter_repositories(limit)]
        return sorted(repositories, key=lambda repository: repository.position)

    async def iter_repositories(self, limit: int = 100) -> AsyncIterator[Repository]:
        """Отдаёт репозитории по мере готовности, не накапливая весь топ в памяти."""
        top = await self._get_top_repositories(limit)
        since = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        tasks = [
            asyncio.create_task(self._build_repository(item, position, since))
            for position, item in enumerate(top, start=1)
        ]
        try:
            for finished in asyncio.as_completed(tasks):
                repository = await finished
                if repository is not None:
                    yield repository
        finally:
            for task in tasks:
                task.cancel()

    async def _get_top_repositories(self, limit: int) -> list[dict[str, Any]]:
        data, _ = await self._request(
            "/search/repositories",
            params={"q": "stars:>1", "sort": "stars", "order": "desc", "per_page": min(limit, 100)},
        )
        items: list[dict[str, Any]] = data.get("items", [])
        return items[:limit]

    async def _build_repository(self, item: dict[str, Any], position: int, since: datetime) -> Repository | None:
        owner, name = item["owner"]["login"], item["name"]
        try:
            authors = await self._count_commit_authors(owner, name, since)
        except GithubApiError as exc:
            logger.warning("Пропускаю {owner}/{name}: {error}", owner=owner, name=name, error=exc)
            return None
        return Repository(
            name=name,
            owner=owner,
            position=position,
            stars=item.get("stargazers_count", 0),
            watchers=item.get("watchers_count", 0),
            forks=item.get("forks_count", 0),
            language=item.get("language") or "Unknown",
            authors_commits_num_today=[
                RepositoryAuthorCommitsNum(author=author, commits_num=count) for author, count in authors.most_common()
            ],
        )

    async def _count_commit_authors(self, owner: str, name: str, since: datetime) -> Counter[str]:
        authors: Counter[str] = Counter()
        path: str | None = f"/repos/{owner}/{name}/commits"
        params: dict[str, Any] | None = {"since": since.isoformat(), "per_page": 100}
        for _ in range(self._max_commit_pages):
            if path is None:
                break
            commits, path = await self._request(path, params)
            params = None
            for commit in commits:
                authors[_author_of(commit)] += 1
        return authors

    async def _request(self, path: str, params: dict[str, Any] | None = None) -> tuple[Any, str | None]:
        url = path if path.startswith("http") else f"{self._api_url}{path}"
        for attempt in range(self._max_retries + 1):
            async with self._semaphore:
                await self._rate_limiter.acquire()
                try:
                    async with self._session.get(url, params=params) as response:
                        if response.status == 200:
                            return await response.json(), _next_page(response)
                        wait = _retry_delay(response, attempt)
                        error = f"HTTP {response.status} {url}"
                except (ClientError, TimeoutError) as exc:
                    wait = 2.0**attempt
                    error = f"{type(exc).__name__} {url}"
            if wait is None or attempt == self._max_retries:
                raise GithubApiError(error)
            logger.debug("{error}, повтор через {wait:.1f} с", error=error, wait=wait)
            await asyncio.sleep(wait)
        raise GithubApiError(f"Запрос не выполнен: {url}")


def _author_of(commit: dict[str, Any]) -> str:
    if commit.get("author") and commit["author"].get("login"):
        return str(commit["author"]["login"])
    return str(commit.get("commit", {}).get("author", {}).get("name") or "unknown")


def _next_page(response: ClientResponse) -> str | None:
    link = response.links.get("next")
    return str(link["url"]) if link else None


def _retry_delay(response: ClientResponse, attempt: int) -> float | None:
    if response.status in {403, 429} and response.headers.get("X-RateLimit-Remaining") == "0":
        reset_at = float(response.headers.get("X-RateLimit-Reset", time.time()))
        return min(max(reset_at - time.time(), 0.0) + 1.0, MAX_RATE_LIMIT_WAIT_SECONDS)
    if response.status == 429 or response.status in RETRY_STATUSES:
        return float(response.headers.get("Retry-After", 2.0**attempt))
    return None
