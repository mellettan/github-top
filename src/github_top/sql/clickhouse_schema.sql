CREATE DATABASE IF NOT EXISTS test;

CREATE TABLE IF NOT EXISTS test.repositories
(
    name     String,
    owner    String,
    stars    Int32,
    watchers Int32,
    forks    Int32,
    language String,
    updated  DateTime
) ENGINE = ReplacingMergeTree(updated)
ORDER BY name;

CREATE TABLE IF NOT EXISTS test.repositories_authors_commits
(
    date        Date,
    repo        String,
    author      String,
    commits_num Int32
) ENGINE = ReplacingMergeTree
ORDER BY (date, repo, author);

CREATE TABLE IF NOT EXISTS test.repositories_positions
(
    date     Date,
    repo     String,
    position UInt32
) ENGINE = ReplacingMergeTree
ORDER BY (date, repo);

CREATE TABLE IF NOT EXISTS test.phrases_views
(
    dt          DateTime,
    campaign_id Int32 COMMENT 'Идентификатор рекламной кампании',
    phrase      String COMMENT 'Поисковый запрос',
    views       Int32 COMMENT 'Кумулятивное количество просмотров по запросу за всё время'
) ENGINE = ReplacingMergeTree
ORDER BY (dt, campaign_id, phrase);
