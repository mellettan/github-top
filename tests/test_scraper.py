import asyncio
from collections import defaultdict

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from github_top.github.models import RepositoryAuthorCommitsNum
from github_top.github.scraper import GithubReposScrapper


def commit(login: str | None, name: str = "Someone") -> dict:
    return {"author": {"login": login} if login else None, "commit": {"author": {"name": name}}}


class FakeGithub:
    """Минимальная эмуляция GitHub REST API: поиск, пагинация коммитов, сбои и задержки."""

    def __init__(self) -> None:
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls: defaultdict[str, int] = defaultdict(int)
        self.authorization: set[str | None] = set()
        app = web.Application()
        app.router.add_get("/search/repositories", self.search)
        app.router.add_get("/repos/{owner}/{repo}/commits", self.commits)
        self.server = TestServer(app)

    async def track(self, request: web.Request) -> None:
        self.authorization.add(request.headers.get("Authorization"))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        await asyncio.sleep(0.01)
        self.in_flight -= 1

    async def search(self, request: web.Request) -> web.Response:
        await self.track(request)
        assert request.query["sort"] == "stars"
        items = [
            {"name": "linux", "owner": {"login": "torvalds"}, "stargazers_count": 300, "language": "C"},
            {"name": "react", "owner": {"login": "facebook"}, "stargazers_count": 200, "language": None},
            {"name": "empty", "owner": {"login": "ghost"}, "stargazers_count": 100},
            {"name": "flaky", "owner": {"login": "acme"}, "stargazers_count": 50},
        ]
        return web.json_response({"items": items[: int(request.query["per_page"])]})

    async def commits(self, request: web.Request) -> web.Response:
        await self.track(request)
        repo = request.match_info["repo"]
        self.calls[repo] += 1
        if repo == "empty":
            return web.json_response({"message": "Git Repository is empty."}, status=409)
        if repo == "flaky" and self.calls[repo] == 1:
            return web.json_response({}, status=502, headers={"Retry-After": "0"})
        if repo == "linux" and request.query.get("page") != "2":
            next_url = self.server.make_url("/repos/torvalds/linux/commits?page=2&per_page=100")
            return web.json_response(
                [commit("torvalds"), commit("gregkh")], headers={"Link": f'<{next_url}>; rel="next"'}
            )
        if repo == "linux":
            return web.json_response([commit("torvalds"), commit(None, "Bot")])
        return web.json_response([commit("gaearon")])


@pytest.fixture
async def github():
    fake = FakeGithub()
    await fake.server.start_server()
    yield fake
    await fake.server.close()


def make_scraper(github: FakeGithub, **kwargs) -> GithubReposScrapper:
    return GithubReposScrapper(access_token="secret", api_url=str(github.server.make_url("")), max_rps=1000, **kwargs)


async def test_collects_top_with_paginated_commit_authors(github: FakeGithub):
    async with make_scraper(github) as scraper:
        repositories = await scraper.get_repositories(limit=4)

    assert [(r.position, r.owner, r.name) for r in repositories] == [
        (1, "torvalds", "linux"),
        (2, "facebook", "react"),
        (4, "acme", "flaky"),
    ]
    linux = repositories[0]
    assert linux.stars == 300
    assert linux.authors_commits_num_today == [
        RepositoryAuthorCommitsNum("torvalds", 2),
        RepositoryAuthorCommitsNum("gregkh", 1),
        RepositoryAuthorCommitsNum("Bot", 1),
    ]
    assert repositories[1].language == "Unknown"
    assert github.calls["flaky"] == 2
    assert github.authorization == {"Bearer secret"}


async def test_respects_max_concurrent_requests(github: FakeGithub):
    async with make_scraper(github, max_concurrent=1) as scraper:
        await scraper.get_repositories(limit=4)

    assert github.max_in_flight == 1


async def test_limit_trims_top(github: FakeGithub):
    async with make_scraper(github) as scraper:
        repositories = await scraper.get_repositories(limit=1)

    assert [r.name for r in repositories] == ["linux"]
