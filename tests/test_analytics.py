import os
from datetime import date, datetime, timedelta

import pytest
from aiochclient import ChClient
from aiohttp import ClientSession

from github_top.analytics import phrases_views_by_hour
from github_top.sql import load_sql, split_statements

URL = os.getenv("TEST_CLICKHOUSE_URL")
pytestmark = [pytest.mark.clickhouse, pytest.mark.skipif(URL is None, reason="TEST_CLICKHOUSE_URL не задан")]

DAY = date(2025, 1, 1)
DRESS_VIEWS = [0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 3, 5, 5, 6, 8, 9, 10, 11, 11, 11, 12, 13, 13, 15, 15]


@pytest.fixture
async def clickhouse():
    async with ClientSession() as session:
        admin = ChClient(session, url=URL)
        for statement in split_statements(load_sql("clickhouse_schema.sql")):
            await admin.execute(statement)
        client = ChClient(session, url=URL, database="test")
        await client.execute("TRUNCATE TABLE test.phrases_views")
        yield client


async def insert(client: ChClient, rows: list[tuple[datetime, int, str, int]]) -> None:
    await client.execute("INSERT INTO test.phrases_views (dt, campaign_id, phrase, views) VALUES", *rows)


async def test_views_by_hour_from_cumulative_counter(clickhouse: ChClient):
    start = datetime(2025, 1, 1, 11, 50)
    await insert(
        clickhouse,
        [(start + timedelta(minutes=10 * i), 1111111, "платье", views) for i, views in enumerate(DRESS_VIEWS)],
    )
    await insert(clickhouse, [(datetime(2025, 1, 1, 12, 0), 2222222, "платье", 100)])

    rows = await phrases_views_by_hour(clickhouse, 1111111, DAY)

    assert rows == [("платье", [(15, 4), (14, 6), (13, 4), (12, 1)])]


async def test_first_hour_counts_from_previous_day(clickhouse: ChClient):
    await insert(
        clickhouse,
        [
            (datetime(2024, 12, 31, 23, 40), 1, "куртка", 40),
            (datetime(2025, 1, 1, 0, 10), 1, "куртка", 43),
            (datetime(2025, 1, 1, 1, 30), 1, "куртка", 50),
            (datetime(2025, 1, 2, 0, 10), 1, "куртка", 70),
        ],
    )

    rows = await phrases_views_by_hour(clickhouse, 1, DAY)

    assert rows == [("куртка", [(1, 7), (0, 3)])]
