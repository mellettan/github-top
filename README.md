# github-top — топ GitHub и активность авторов в ClickHouse

[![CI](https://github.com/mellettan/github-top/actions/workflows/ci.yml/badge.svg)](https://github.com/mellettan/github-top/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12-3776AB?logo=python&logoColor=white)
![asyncio](https://img.shields.io/badge/asyncio-aiohttp-2C5BB4)
![ClickHouse](https://img.shields.io/badge/ClickHouse-25.8-FFCC01?logo=clickhouse&logoColor=black)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-asyncpg-4169E1?logo=postgresql&logoColor=white)

Асинхронный сбор топ-100 репозиториев GitHub по звёздам вместе с авторами коммитов за текущие сутки и потоковая загрузка в ClickHouse. Плюс аналитический SQL по кумулятивным счётчикам и небольшой FastAPI-сервис с пулом соединений asyncpg.

```
$ github-top top -n 4
  1. codecrafters-io/build-your-own-x ★453120 — -
  2. sindresorhus/awesome ★402871 — -
  3. freeCodeCamp/freeCodeCamp ★425310 — renovate[bot] (5), ojeytonwilliams (2)
  4. public-apis/public-apis ★361040 — -
```

## Что внутри

### Скрапер GitHub (`github_top.github`)

- **Ограничение конкурентности (MCR)** — `asyncio.Semaphore` на все запросы к API.
- **Ограничение RPS** — `RateLimiter` резервирует под блокировкой равномерные слоты времени, поэтому одновременно запущенные корутины не уходят пачкой, а распределяются с шагом `1 / rps`.
- **Устойчивость** — 5xx и 429 повторяются с экспоненциальной задержкой и учётом `Retry-After`; при исчерпании лимита GitHub (`403` + `X-RateLimit-Remaining: 0`) скрапер ждёт `X-RateLimit-Reset`. Репозиторий, для которого коммиты получить не удалось (например, пустой — `409`), пропускается с предупреждением, а не роняет весь сбор.
- **Пагинация** — коммиты за сутки собираются по `Link: rel="next"`, а не только первая сотня.
- **Потоковая выдача** — `iter_repositories()` отдаёт репозитории по мере готовности через `asyncio.as_completed`.

### Загрузка в ClickHouse (`github_top.clickhouse`)

`RepositoriesLoader` читает поток репозиториев и пишет три таблицы (`repositories`, `repositories_positions`, `repositories_authors_commits`). Для каждой таблицы свой буфер, который сбрасывается в ClickHouse при достижении `CLICKHOUSE_BATCH_SIZE` строк, поэтому потребление памяти ограничено размером батча, а не размером топа и числом авторов. Таблицы на `ReplacingMergeTree`, поэтому повторная загрузка за тот же день не создаёт дублей.

```mermaid
flowchart LR
    GH[GitHub REST API] -->|semaphore + RPS limiter| S[GithubReposScrapper]
    S -->|async iterator| L[RepositoriesLoader]
    L -->|батчи| R[(repositories)]
    L -->|батчи| P[(repositories_positions)]
    L -->|батчи| A[(repositories_authors_commits)]
```

### Аналитика просмотров (`sql/phrases_views_by_hour.sql`)

В `phrases_views` хранится кумулятивный счётчик просмотров по поисковой фразе. Запрос считает просмотры за каждый час дня как прирост максимума часа относительно предыдущего часа (`lagInFrame`), отбрасывает часы без прироста и собирает результат в массив от позднего часа к раннему:

```
phrase   views_by_hour
платье   [(15, 4), (14, 6), (13, 4), (12, 1)]
```

Чтобы первый час дня не получил весь накопленный счётчик, в расчёт берутся и данные за предыдущие сутки. Запрос параметризован кампанией и датой и покрыт тестом на настоящем ClickHouse.

### API на PostgreSQL (`github_top.pg_api`)

`GET /api/db_version` — версия PostgreSQL. Пул `asyncpg` создаётся в `lifespan` и хранится в `app.state`, соединение выдаётся зависимостью FastAPI на время запроса — без глобальных объектов. Если база недоступна, ответ `503`.

## Запуск

```bash
cp .env.example .env              # GITHUB_TOKEN поднимает лимит API с 60 до 5000 запросов в час
docker compose up -d postgres clickhouse

uv sync
uv run github-top top -n 10                              # топ в консоль
uv run github-top load                                   # топ → ClickHouse
uv run github-top phrases --campaign 1111111 --date 2025-01-01
uv run uvicorn github_top.pg_api:create_app --factory    # API
```

Или целиком в Docker: `docker compose up` поднимает API и базы, загрузка запускается отдельной задачей `docker compose run --rm loader`.

## Тесты

```bash
docker compose up -d postgres clickhouse
TEST_POSTGRES_DSN=postgresql://github_top:github_top@localhost:5432/github_top \
TEST_CLICKHOUSE_URL=http://localhost:8123 \
uv run pytest
```

- Скрапер проверяется против локального aiohttp-сервера, который эмулирует GitHub API: пагинацию через `Link`, сбой `502` с повтором, пустой репозиторий `409`; отдельно проверяется, что одновременно выполняется не больше `max_concurrent` запросов.
- `RateLimiter` — с подменёнными часами, без реального ожидания.
- Загрузчик — что ни один батч не превышает `batch_size`.
- SQL и API — на настоящих ClickHouse и PostgreSQL (в CI — service-контейнеры); без переменных окружения эти тесты пропускаются.
