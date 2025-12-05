from collections.abc import AsyncIterator
from datetime import date

from github_top.clickhouse.loader import RepositoriesLoader
from github_top.github.models import Repository, RepositoryAuthorCommitsNum


class RecordingClient:
    def __init__(self) -> None:
        self.batches: list[tuple[str, list[tuple]]] = []

    async def execute(self, query: str, *rows) -> None:
        self.batches.append((query.split()[2], list(rows)))


async def repositories(count: int, authors: int) -> AsyncIterator[Repository]:
    for index in range(count):
        yield Repository(
            name=f"repo{index}",
            owner="org",
            position=index + 1,
            stars=100 - index,
            watchers=10,
            forks=5,
            language="Python",
            authors_commits_num_today=[RepositoryAuthorCommitsNum(f"dev{a}", a + 1) for a in range(authors)],
        )


async def test_inserts_in_batches_with_bounded_buffer():
    client = RecordingClient()
    loader = RepositoriesLoader(client, "test", batch_size=2)

    stats = await loader.load(repositories(count=3, authors=3), day=date(2025, 12, 3))

    assert (stats.repositories, stats.positions, stats.authors_commits) == (3, 3, 9)
    assert all(len(rows) <= 2 for _, rows in client.batches)
    by_table: dict[str, list[tuple]] = {}
    for table, rows in client.batches:
        by_table.setdefault(table, []).extend(rows)
    assert by_table["test.repositories_positions"] == [
        (date(2025, 12, 3), "org/repo0", 1),
        (date(2025, 12, 3), "org/repo1", 2),
        (date(2025, 12, 3), "org/repo2", 3),
    ]
    assert len(by_table["test.repositories_authors_commits"]) == 9
    assert by_table["test.repositories"][0][:6] == ("org/repo0", "org", 100, 10, 5, "Python")
    assert stats.batches == len(client.batches)


async def test_empty_stream_makes_no_inserts():
    client = RecordingClient()

    stats = await RepositoriesLoader(client, "test").load(repositories(0, 0))

    assert client.batches == []
    assert stats.batches == 0
