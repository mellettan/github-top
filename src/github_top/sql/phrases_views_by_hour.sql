WITH
    hourly AS (
        SELECT phrase, toStartOfHour(dt) AS hour, max(views) AS views
        FROM phrases_views
        WHERE campaign_id = {campaign_id}
          AND dt >= toDateTime({day}) - INTERVAL 1 DAY
          AND dt < toDateTime({day}) + INTERVAL 1 DAY
        GROUP BY phrase, hour
    ),
    deltas AS (
        SELECT
            phrase,
            hour,
            views - lagInFrame(views, 1, 0) OVER (
                PARTITION BY phrase ORDER BY hour ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
            ) AS delta
        FROM hourly
    )
SELECT phrase, arrayReverseSort(x -> x.1, groupArray((toHour(hour), delta))) AS views_by_hour
FROM deltas
WHERE toDate(hour) = {day} AND delta > 0
GROUP BY phrase
ORDER BY phrase
