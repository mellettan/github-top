from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Protocol

from loguru import logger

from github_top.github.models import Repository

Row = tuple[Any, ...]


class ClickHouseClient(Protocol):
    async def execute(self, query: str, *args: Any) -> None: ...


@dataclass(slots=True)
class LoadStats:
    repositories: int = 0
    positions: int = 0
    authors_commits: int = 0
    batches: int = 0


@dataclass(slots=True)
class _Table:
    insert: str
    rows: list[Row] = field(default_factory=list)


class RepositoriesLoader:
    """Потоковая загрузка репозиториев в ClickHouse батчами по `batch_size` строк.

    Строки копятся в буфере отдельной таблицы и уходят в ClickHouse, как только буфер
    заполнился, поэтому память не зависит от размера топа и числа авторов.
    """

    def __init__(self, client: ClickHouseClient, database: str, batch_size: int = 1000) -> None:
        self._client = client
        self._batch_size = batch_size
        self._tables = {
            "repositories": _Table(
                f"INSERT INTO {database}.repositories (name, owner, stars, watchers, forks, language, updated) VALUES"
            ),
            "positions": _Table(f"INSERT INTO {database}.repositories_positions (date, repo, position) VALUES"),
            "authors_commits": _Table(
                f"INSERT INTO {database}.repositories_authors_commits (date, repo, author, commits_num) VALUES"
            ),
        }

    async def load(self, repositories: AsyncIterator[Repository], day: date | None = None) -> LoadStats:
        day = day or datetime.now(UTC).date()
        updated = datetime.now(UTC).replace(microsecond=0, tzinfo=None)
        stats = LoadStats()
        async for repository in repositories:
            full_name = f"{repository.owner}/{repository.name}"
            await self._add(
                "repositories",
                (
                    full_name,
                    repository.owner,
                    repository.stars,
                    repository.watchers,
                    repository.forks,
                    repository.language,
                    updated,
                ),
                stats,
            )
            await self._add("positions", (day, full_name, repository.position), stats)
            for author in repository.authors_commits_num_today:
                await self._add("authors_commits", (day, full_name, author.author, author.commits_num), stats)
        for name in self._tables:
            await self._flush(name, stats)
        logger.info("Загружено в ClickHouse: {stats}", stats=stats)
        return stats

    async def _add(self, name: str, row: Row, stats: LoadStats) -> None:
        table = self._tables[name]
        table.rows.append(row)
        setattr(stats, name, getattr(stats, name) + 1)
        if len(table.rows) >= self._batch_size:
            await self._flush(name, stats)

    async def _flush(self, name: str, stats: LoadStats) -> None:
        table = self._tables[name]
        if not table.rows:
            return
        await self._client.execute(table.insert, *table.rows)
        stats.batches += 1
        table.rows.clear()
