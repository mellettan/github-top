import os

import pytest
from httpx import ASGITransport, AsyncClient

from github_top.config import Settings
from github_top.pg_api import create_app

DSN = os.getenv("TEST_POSTGRES_DSN")
pytestmark = [pytest.mark.postgres, pytest.mark.skipif(DSN is None, reason="TEST_POSTGRES_DSN не задан")]


async def test_db_version_uses_pool_from_lifespan():
    app = create_app(Settings(_env_file=None, postgres_dsn=DSN))

    transport = ASGITransport(app=app)
    async with app.router.lifespan_context(app), AsyncClient(transport=transport, base_url="http://test") as client:
        responses = [await client.get("/api/db_version") for _ in range(3)]

    assert all(response.status_code == 200 for response in responses)
    assert responses[0].json().startswith("PostgreSQL")
