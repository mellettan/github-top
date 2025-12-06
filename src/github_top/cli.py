import argparse
import asyncio
from collections.abc import Sequence
from datetime import UTC, date, datetime

from aiochclient import ChClient
from aiohttp import ClientSession

from github_top.analytics import phrases_views_by_hour
from github_top.clickhouse.loader import RepositoriesLoader
from github_top.config import Settings
from github_top.github.scraper import GithubReposScrapper
from github_top.sql import load_sql, split_statements


def make_scraper(settings: Settings) -> GithubReposScrapper:
    return GithubReposScrapper(
        access_token=settings.github_token.get_secret_value() if settings.github_token else None,
        max_concurrent=settings.github_max_concurrent_requests,
        max_rps=settings.github_max_rps,
        api_url=settings.github_api_url,
        max_commit_pages=settings.github_max_commit_pages,
    )


def make_clickhouse(session: ClientSession, settings: Settings, database: str | None = None) -> ChClient:
    return ChClient(
        session,
        url=settings.clickhouse_url,
        user=settings.clickhouse_user,
        password=settings.clickhouse_password.get_secret_value(),
        database=database or "default",
    )


async def show_top(settings: Settings, count: int) -> None:
    async with make_scraper(settings) as scraper:
        repositories = await scraper.get_repositories(settings.github_top_limit)
    for repository in repositories[:count]:
        authors = ", ".join(f"{a.author} ({a.commits_num})" for a in repository.authors_commits_num_today[:3])
        print(f"{repository.position:>3}. {repository.owner}/{repository.name} ★{repository.stars} — {authors or '-'}")


async def load(settings: Settings) -> None:
    async with ClientSession() as session, make_scraper(settings) as scraper:
        admin = make_clickhouse(session, settings)
        for statement in split_statements(load_sql("clickhouse_schema.sql")):
            await admin.execute(statement)
        client = make_clickhouse(session, settings, settings.clickhouse_database)
        loader = RepositoriesLoader(client, settings.clickhouse_database, settings.clickhouse_batch_size)
        stats = await loader.load(scraper.iter_repositories(settings.github_top_limit))
    print(
        f"Загружено: {stats.repositories} репозиториев, {stats.authors_commits} строк авторов, {stats.batches} батчей"
    )


async def phrases(settings: Settings, campaign_id: int, day: date) -> None:
    async with ClientSession() as session:
        rows = await phrases_views_by_hour(
            make_clickhouse(session, settings, settings.clickhouse_database), campaign_id, day
        )
    print(f"{'phrase':<20} views_by_hour")
    for phrase, views in rows:
        print(f"{phrase:<20} {views}")


def main(argv: Sequence[str] | None = None) -> None:
    """CLI: `github-top top | load | phrases`."""
    parser = argparse.ArgumentParser(prog="github-top")
    commands = parser.add_subparsers(dest="command", required=True)
    top = commands.add_parser("top", help="вывести топ репозиториев с авторами коммитов за сегодня")
    top.add_argument("-n", type=int, default=10, help="сколько строк вывести")
    commands.add_parser("load", help="собрать топ и загрузить в ClickHouse")
    report = commands.add_parser("phrases", help="просмотры по фразам по часам")
    report.add_argument("--campaign", type=int, required=True)
    report.add_argument("--date", type=date.fromisoformat, default=datetime.now(UTC).date())
    args = parser.parse_args(argv)

    settings = Settings()
    if args.command == "top":
        asyncio.run(show_top(settings, args.n))
    elif args.command == "load":
        asyncio.run(load(settings))
    else:
        asyncio.run(phrases(settings, args.campaign, args.date))


if __name__ == "__main__":
    main()
