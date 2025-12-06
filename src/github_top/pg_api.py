from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, status

from github_top.config import Settings


async def get_pg_connection(request: Request) -> AsyncIterator[asyncpg.Connection]:
    """Соединение из пула приложения на время запроса; пул создаётся в lifespan, а не глобально."""
    pool: asyncpg.Pool = request.app.state.pg_pool
    try:
        async with pool.acquire() as connection:
            yield connection
    except (OSError, asyncpg.PostgresConnectionError) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "База данных недоступна") from exc


async def get_db_version(conn: Annotated[asyncpg.Connection, Depends(get_pg_connection)]) -> str:
    version: str = await conn.fetchval("SELECT version()")
    return version


def register_routes(app: FastAPI) -> None:
    router = APIRouter(prefix="/api")
    router.add_api_route(path="/db_version", endpoint=get_db_version, methods=["GET"])
    app.include_router(router)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.pg_pool = await asyncpg.create_pool(
            dsn=settings.postgres_dsn,
            min_size=settings.postgres_pool_min_size,
            max_size=settings.postgres_pool_max_size,
        )
        try:
            yield
        finally:
            await app.state.pg_pool.close()

    app = FastAPI(title="github-top", lifespan=lifespan)
    register_routes(app)
    return app
