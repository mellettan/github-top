from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RepositoryAuthorCommitsNum:
    author: str
    commits_num: int


@dataclass(frozen=True, slots=True)
class Repository:
    name: str
    owner: str
    position: int
    stars: int
    watchers: int
    forks: int
    language: str
    authors_commits_num_today: list[RepositoryAuthorCommitsNum]
