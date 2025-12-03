from importlib.resources import files


def load_sql(name: str) -> str:
    """Текст SQL-файла из пакета `github_top/sql`."""
    return files("github_top").joinpath("sql", name).read_text(encoding="utf-8")


def split_statements(script: str) -> list[str]:
    """Делит SQL-скрипт на отдельные запросы: HTTP-интерфейс ClickHouse принимает по одному."""
    return [statement.strip() for statement in script.split(";") if statement.strip()]
