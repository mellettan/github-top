from datetime import date
from typing import Any, Protocol

from github_top.sql import load_sql


class ClickHouseReader(Protocol):
    async def fetch(self, query: str, *args: Any, params: dict[str, Any] | None = None) -> list[Any]: ...


async def phrases_views_by_hour(
    client: ClickHouseReader, campaign_id: int, day: date
) -> list[tuple[str, list[tuple[int, int]]]]:
    """Просмотры по поисковым фразам кампании за каждый час дня `day`, от позднего часа к раннему.

    В таблице хранится кумулятивный счётчик, поэтому просмотры за час — это прирост
    максимума часа относительно предыдущего часа. Базой для первого часа дня служат
    данные за предыдущие сутки; часы без прироста не выводятся.
    """
    rows = await client.fetch(load_sql("phrases_views_by_hour.sql"), params={"campaign_id": campaign_id, "day": day})
    return [(row["phrase"], [(int(hour), int(views)) for hour, views in row["views_by_hour"]]) for row in rows]
